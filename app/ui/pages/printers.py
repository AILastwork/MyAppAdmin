from __future__ import annotations

from pathlib import Path
import re
from threading import Event

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import DEFAULT_PRINTER_CONFIG_FILE, AppConfig
from app.services.ad_directory import build_login_candidates, parse_full_name
from app.services.printers.base import (
    PrinterAddressBookEntry,
    PrinterDevice,
    add_printer_device,
    load_printer_devices,
    normalize_printer_ip,
    remove_printer_device,
)
from app.services.printers.kyocera import (
    KYOCERA_COMPATIBILITY_NOTE,
    KyoceraAdapter,
    KyoceraOperationCancelled,
    provision_scan_folder,
    scan_folder_exists,
)
from app.ui.ad_admin_auth import request_privileged_operation_authorization
from app.ui.context import PageContext
from app.ui.widgets import Card, button, page_title


DEFAULT_PRINTER_EMAIL_DOMAIN = "mkd-osnova.ru"


class KyoceraAddWorker(QObject):
    output = Signal(str)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, device: PrinterDevice, entry: PrinterAddressBookEntry, config: AppConfig) -> None:
        super().__init__()
        self.device = device
        self.entry = entry
        self.config = config
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = KyoceraAdapter().add_entry(
                self.device,
                self.entry,
                self.config,
                on_output=self.output.emit,
                cancel_event=self._cancel_event,
            )
        except KyoceraOperationCancelled as exc:
            self.cancelled.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class PrintersPage(QWidget):
    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.local_printer_config_file = self.context.config_path.with_name("printers.local.json")
        self._auto_login = ""
        self._auto_email = ""
        self._kyocera_thread: QThread | None = None
        self._kyocera_worker: KyoceraAddWorker | None = None
        self._kyocera_device = None
        self._kyocera_entry: PrinterAddressBookEntry | None = None
        self._kyocera_cancel_requested = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("Принтеры / адресные книги МФУ"))

        card = Card("Устройства")
        actions = QHBoxLayout()
        self.load_btn = button("Выбрать printers.json", primary=True)
        self.load_btn.clicked.connect(self.select_printer_config)
        refresh_btn = button("Обновить список")
        refresh_btn.clicked.connect(self.refresh)
        self.delete_printer_btn = button("Удалить выбранный", danger=True)
        self.delete_printer_btn.clicked.connect(self.remove_selected_printer)
        actions.addWidget(self.load_btn)
        actions.addWidget(refresh_btn)
        actions.addWidget(self.delete_printer_btn)
        actions.addStretch(1)
        card.layout.addLayout(actions)
        self.printer_config_path = QLabel()
        self.printer_config_path.setWordWrap(True)
        self.printer_config_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.layout.addWidget(self.printer_config_path)

        add_device_row = QHBoxLayout()
        add_device_row.addWidget(QLabel("IP адрес"))
        self.printer_ip = QLineEdit()
        self.printer_ip.setPlaceholderText("192.168.10.25")
        self.printer_ip.returnPressed.connect(self.add_printer_by_ip)
        self.printer_name = QLineEdit()
        self.printer_name.setPlaceholderText("Имя / hostname, например KM1E33BC")
        self.printer_model = QLineEdit()
        self.printer_model.setPlaceholderText("Модель, например ECOSYS MA4500x")
        add_device_btn = button("Добавить принтер по IP")
        add_device_btn.clicked.connect(self.add_printer_by_ip)
        add_device_row.addWidget(self.printer_ip, 1)
        add_device_row.addWidget(self.printer_name, 1)
        add_device_row.addWidget(self.printer_model, 1)
        add_device_row.addWidget(add_device_btn)
        card.layout.addLayout(add_device_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Название", "Марка", "Модель", "Host", "Площадка"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        card.layout.addWidget(self.table)

        support_info = QLabel(f"<b>Поддержка скрипта:</b> {KYOCERA_COMPATIBILITY_NOTE}")
        support_info.setWordWrap(True)
        support_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.layout.addWidget(support_info)

        form = QFormLayout()
        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("Иванов Иван Сергеевич")
        self.full_name.setToolTip("При вводе ФИО login и email формируются автоматически.")
        self.full_name.textChanged.connect(self.autofill_identity)
        self.login = QLineEdit()
        self.login.setPlaceholderText("i.ivanov")
        self.login.setToolTip("Формируется из ФИО. Поле можно исправить вручную.")
        self.login.textEdited.connect(self.sync_email_from_login)
        self.email = QLineEdit()
        self.email.setPlaceholderText("i.ivanov@mkd-osnova.ru")
        self.email.setToolTip(
            f"Автоматически формируется в домене {DEFAULT_PRINTER_EMAIL_DOMAIN}. Поле можно исправить вручную."
        )
        self.email.textEdited.connect(self.mark_email_as_manual)
        form.addRow("ФИО", self.full_name)
        form.addRow("Login", self.login)
        form.addRow("Email", self.email)
        card.layout.addLayout(form)

        kyocera_actions = QHBoxLayout()
        self.preview_btn = button("Предпросмотр Kyocera-записи")
        self.preview_btn.clicked.connect(self.preview_kyocera)
        self.add_kyocera_btn = button("Добавить в Kyocera", primary=True)
        self.add_kyocera_btn.clicked.connect(self.add_kyocera)
        kyocera_actions.addWidget(self.preview_btn)
        kyocera_actions.addWidget(self.add_kyocera_btn)
        kyocera_actions.addStretch(1)
        card.layout.addLayout(kyocera_actions)

        self.kyocera_progress_frame = QFrame()
        self.kyocera_progress_frame.setProperty("role", "mailProgress")
        progress_layout = QVBoxLayout(self.kyocera_progress_frame)
        progress_layout.setContentsMargins(12, 10, 12, 10)
        progress_layout.setSpacing(6)
        progress_title = QLabel("Добавление в адресную книгу Kyocera")
        progress_title.setObjectName("ProgressTitle")
        self.kyocera_progress_status = QLabel("Ожидание запуска")
        self.kyocera_progress_status.setObjectName("ProgressStatus")
        self.kyocera_progress_status.setWordWrap(True)
        self.kyocera_progress_bar = QProgressBar()
        self.kyocera_progress_bar.setRange(0, 100)
        self.kyocera_progress_bar.setValue(0)
        self.kyocera_progress_bar.setTextVisible(True)
        progress_layout.addWidget(progress_title)
        progress_layout.addWidget(self.kyocera_progress_status)
        progress_layout.addWidget(self.kyocera_progress_bar)
        progress_actions = QHBoxLayout()
        progress_actions.addStretch(1)
        self.cancel_kyocera_btn = button("Отменить операцию")
        self.cancel_kyocera_btn.clicked.connect(self.cancel_kyocera)
        progress_actions.addWidget(self.cancel_kyocera_btn)
        progress_layout.addLayout(progress_actions)
        self.kyocera_progress_frame.setVisible(False)
        card.layout.addWidget(self.kyocera_progress_frame)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        card.layout.addWidget(self.preview)
        layout.addWidget(card, 1)
        self.refresh()

    def select_printer_config(self, _checked: bool = False) -> None:
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Выбрать printers.json",
            str(self.context.config_path.parent),
            "JSON (*.json);;Все файлы (*.*)",
        )
        if not filename:
            return

        selected_path = Path(filename)
        try:
            devices = load_printer_devices(selected_path)
        except Exception as exc:
            self.context.audit.log(
                "printers_config_select",
                object_type="printers",
                object_name=str(selected_path),
                result="ERROR",
                message=str(exc),
            )
            QMessageBox.warning(
                self,
                "Загрузить printers.json",
                f"Не удалось прочитать файл:\n{selected_path}\n\n{exc}",
            )
            return

        self.context.config.printer_config_file = str(selected_path)
        if self.context.on_config_changed:
            self.context.on_config_changed()
        else:
            self.context.config.save(self.context.config_path)
            self.refresh()
        self.context.audit.log(
            "printers_config_select",
            object_type="printers",
            object_name=str(selected_path),
            result="SUCCESS",
            message=f"Выбран printers.json, устройств: {len(devices)}",
        )
        QMessageBox.information(
            self,
            "Загрузить printers.json",
            f"Файл загружен и сохранен в настройках:\n{selected_path}\n\n"
            f"Устройств: {len(devices)}",
        )

    def autofill_identity(self, _text: str = "") -> None:
        generated_login, _generated_email = printer_identity_from_full_name(self.full_name.text())
        current_login = self.login.text().strip()
        if not current_login or current_login == self._auto_login:
            self.login.setText(generated_login)
            self._auto_login = generated_login

        actual_login = self.login.text().strip()
        generated_email = f"{actual_login}@{DEFAULT_PRINTER_EMAIL_DOMAIN}" if actual_login else ""
        current_email = self.email.text().strip()
        if not current_email or current_email == self._auto_email:
            self.email.setText(generated_email)
            self._auto_email = generated_email

    def sync_email_from_login(self, text: str) -> None:
        self._auto_login = ""
        generated_email = f"{text.strip()}@{DEFAULT_PRINTER_EMAIL_DOMAIN}" if text.strip() else ""
        current_email = self.email.text().strip()
        if not current_email or current_email == self._auto_email:
            self.email.setText(generated_email)
            self._auto_email = generated_email

    def mark_email_as_manual(self, _text: str = "") -> None:
        self._auto_email = ""

    def refresh(self) -> None:
        if hasattr(self, "printer_config_path"):
            self.printer_config_path.setText(
                f"Текущий printers.json: {self.context.config.printer_config_file}\n"
                f"Пример общего списка: {DEFAULT_PRINTER_CONFIG_FILE} (путь можно изменить)"
            )
        source_errors: list[str] = []
        try:
            shared_devices = load_printer_devices(self.context.config.printer_config_file)
        except Exception as exc:
            shared_devices = []
            source_errors.append(f"Общий printers.json недоступен: {exc}")
        try:
            local_devices = load_printer_devices(self.local_printer_config_file)
        except Exception as exc:
            local_devices = []
            source_errors.append(f"Локальный printers.local.json недоступен: {exc}")

        self.devices, self.device_sources = merge_printer_devices_with_sources(shared_devices, local_devices)
        self.table.setRowCount(0)
        for device in self.devices:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, value in enumerate([device.name, device.vendor, device.model, device.host, device.location]):
                self.table.setItem(row, column, QTableWidgetItem(value))
        message = (
            f"Загружено устройств: {len(self.devices)} "
            f"(общих: {len(shared_devices)}, локальных: {len(local_devices)})"
        )
        if source_errors:
            message += "; " + "; ".join(source_errors)
            if hasattr(self, "preview"):
                self.preview.setPlainText("\n".join(source_errors))
        self.context.audit.log("printers_load", object_type="printers", message=message)

    def add_printer_by_ip(self, _checked: bool = False) -> None:
        try:
            normalized_ip = normalize_printer_ip(self.printer_ip.text())
            if any(device.host.strip().lower() == normalized_ip.lower() for device in self.devices):
                raise ValueError(f"Принтер с IP {normalized_ip} уже существует.")
            device = add_printer_device(
                self.local_printer_config_file,
                normalized_ip,
                name=self.printer_name.text(),
                model=self.printer_model.text(),
            )
        except Exception as exc:
            self.context.audit.log(
                "printer_add",
                object_type="printer",
                object_name=self.printer_ip.text().strip(),
                result="ERROR",
                message=str(exc),
            )
            QMessageBox.warning(self, "Добавить принтер", str(exc))
            return

        self.refresh()
        for row, current in enumerate(self.devices):
            if current.host == device.host:
                self.table.selectRow(row)
                break
        self.printer_ip.clear()
        self.printer_name.clear()
        self.printer_model.clear()
        self.context.audit.log(
            "printer_add",
            object_type="printer",
            object_name=device.host,
            result="SUCCESS",
            message=f"Добавлен принтер: {device.name}",
        )
        QMessageBox.information(
            self,
            "Добавить принтер",
            "Принтер добавлен в локальный список:\n"
            f"{device.name}\n{device.host}\n\n"
            f"{self.local_printer_config_file}",
        )

    def remove_selected_printer(self, _checked: bool = False) -> None:
        device = self._selected_device()
        if not device:
            QMessageBox.warning(self, "Удалить принтер", "Выберите принтер в таблице.")
            return

        row = self.table.currentRow()
        source = self.device_sources[row] if 0 <= row < len(self.device_sources) else "unknown"
        if source == "local":
            target_file = self.local_printer_config_file
            question = (
                "Удалить принтер из локального списка этого пользователя?\n\n"
                f"{device.name}\n{device.host}\n\n"
                f"{target_file}"
            )
        elif source == "shared":
            target_file = Path(self.context.config.printer_config_file)
            question = (
                "Удалить принтер из общего printers.json?\n\n"
                f"{device.name}\n{device.host}\n\n"
                f"{target_file}\n\n"
                "Это изменит общий список для всех, кто использует этот файл."
            )
        else:
            QMessageBox.warning(self, "Удалить принтер", "Не удалось определить источник выбранного принтера.")
            return

        if QMessageBox.question(self, "Удалить принтер", question) != QMessageBox.Yes:
            self.context.audit.log(
                "printer_remove",
                object_type="printer",
                object_name=device.host,
                result="CANCELLED",
                message=f"Удаление отменено, источник: {source}",
            )
            return

        try:
            removed = remove_printer_device(target_file, device.host)
            if not removed:
                raise ValueError(f"Принтер {device.host} не найден в {target_file}.")
        except Exception as exc:
            self.context.audit.log(
                "printer_remove",
                object_type="printer",
                object_name=device.host,
                result="ERROR",
                message=str(exc),
            )
            QMessageBox.warning(self, "Удалить принтер", str(exc))
            return

        self.context.audit.log(
            "printer_remove",
            object_type="printer",
            object_name=device.host,
            result="SUCCESS",
            message=f"Удален принтер из {source}: {device.name}",
        )
        self.refresh()
        if self.table.rowCount():
            self.table.selectRow(min(row, self.table.rowCount() - 1))
        self.preview.setPlainText(
            "Принтер удален из списка:\n"
            f"{device.name}\n{device.host}\n\n"
            f"Источник: {'локальный список' if source == 'local' else 'общий printers.json'}"
        )
        QMessageBox.information(self, "Удалить принтер", "Принтер удален из списка.")

    def preview_kyocera(self) -> None:
        device = self._selected_device()
        if not device:
            self.preview.setPlainText("Выберите устройство.")
            return
        try:
            entry = self._entry_from_form()
        except ValueError as exc:
            self.preview.setPlainText(str(exc))
            return
        lines = KyoceraAdapter().build_preview(device, entry)
        self.preview.setPlainText("\n".join(lines))

    def add_kyocera(self) -> None:
        if self._kyocera_thread and self._kyocera_thread.isRunning():
            return
        device = self._selected_device()
        if not device:
            QMessageBox.warning(self, "Kyocera", "Выберите устройство.")
            return
        try:
            entry = self._entry_from_form()
        except ValueError as exc:
            QMessageBox.warning(self, "Kyocera", str(exc))
            return

        question = (
            f"Добавить запись в адресную книгу Kyocera?\n\n"
            f"Устройство: {device.name} ({device.host})\n"
            f"Сотрудник: {entry.full_name}\n"
            f"Login: {entry.login}\n"
            f"Email: {entry.email}\n\n"
            "Пароли из настроек не будут показаны в журнале."
        )
        if QMessageBox.question(self, "Kyocera", question) != QMessageBox.Yes:
            return

        self.preview.clear()
        self._set_kyocera_running(True, "Подготовка подключения...", 3)
        self.preview.appendPlainText(
            f"Запуск: {device.name} ({device.host}), модель: {device.model or 'не указана'}"
        )
        self._kyocera_device = device
        self._kyocera_entry = entry
        self._kyocera_cancel_requested = False
        self._kyocera_thread = QThread(self)
        self._kyocera_worker = KyoceraAddWorker(device, entry, self.context.config)
        self._kyocera_worker.moveToThread(self._kyocera_thread)
        self._kyocera_thread.started.connect(self._kyocera_worker.run)
        self._kyocera_worker.output.connect(self._handle_kyocera_output)
        self._kyocera_worker.finished.connect(self._handle_kyocera_finished)
        self._kyocera_worker.failed.connect(self._handle_kyocera_failed)
        self._kyocera_worker.cancelled.connect(self._handle_kyocera_cancelled)
        self._kyocera_worker.finished.connect(self._kyocera_thread.quit)
        self._kyocera_worker.failed.connect(self._kyocera_thread.quit)
        self._kyocera_worker.cancelled.connect(self._kyocera_thread.quit)
        self._kyocera_thread.finished.connect(self._kyocera_worker.deleteLater)
        self._kyocera_thread.finished.connect(self._kyocera_thread.deleteLater)
        self._kyocera_thread.finished.connect(self._clear_kyocera_worker)
        self._kyocera_thread.start()

    def _handle_kyocera_output(self, line: str) -> None:
        progress, status = kyocera_progress_from_output(line)
        if progress is not None:
            self.kyocera_progress_bar.setValue(max(self.kyocera_progress_bar.value(), progress))
        if status:
            self.kyocera_progress_status.setText(status)
        display_line = kyocera_line_for_preview(line)
        if display_line:
            self.preview.appendPlainText(display_line)

    def _handle_kyocera_finished(self, _result: object) -> None:
        if self._kyocera_cancel_requested:
            message = (
                "Скрипт завершился одновременно с отменой. "
                "Проверьте адресную книгу принтера: уже принятые устройством изменения не откатываются."
            )
            self._set_kyocera_running(False, "Отмена совпала с завершением операции.", 100)
            self.preview.appendPlainText(message)
            device = self._kyocera_device
            self.context.audit.log(
                "kyocera_add",
                object_type="printer",
                object_name=device.host if device else "",
                result="WARNING",
                message=message,
            )
            return
        self._set_kyocera_running(False, "Контакт успешно добавлен.", 100)
        device = self._kyocera_device
        entry = self._kyocera_entry
        if device is None or entry is None:
            return
        self.context.audit.log(
            "kyocera_add",
            object_type="printer",
            object_name=device.host,
            result="SUCCESS",
            message=f"Добавлен контакт: {entry.login}",
        )
        self._offer_scan_folder_creation(entry)

    def _handle_kyocera_failed(self, message: str) -> None:
        self._set_kyocera_running(False, "Операция завершилась ошибкой.", 100)
        self.preview.appendPlainText(f"ОШИБКА: {message}")
        device = self._kyocera_device
        self.context.audit.log(
            "kyocera_add",
            object_type="printer",
            object_name=device.host if device else "",
            result="ERROR",
            message=message,
        )
        QMessageBox.critical(self, "Kyocera", message)

    def _handle_kyocera_cancelled(self, message: str) -> None:
        self._set_kyocera_running(
            False,
            "Операция отменена. Дочерний процесс остановлен.",
            self.kyocera_progress_bar.value(),
        )
        self.preview.appendPlainText(message)
        device = self._kyocera_device
        self.context.audit.log(
            "kyocera_add",
            object_type="printer",
            object_name=device.host if device else "",
            result="CANCELLED",
            message=message,
        )

    def cancel_kyocera(self, _checked: bool = False) -> None:
        if not self.has_active_operation():
            return
        if QMessageBox.question(
            self,
            "Отменить операцию",
            "Остановить добавление пользователя в адресную книгу принтера?",
        ) != QMessageBox.Yes:
            return
        self._request_kyocera_cancel()

    def has_active_operation(self) -> bool:
        return bool(self._kyocera_thread and self._kyocera_thread.isRunning())

    def cancel_active_operation(self, wait_ms: int = 5000) -> bool:
        if not self.has_active_operation():
            return True
        self._request_kyocera_cancel()
        thread = self._kyocera_thread
        if thread is None:
            return True
        thread.requestInterruption()
        thread.quit()
        return thread.wait(wait_ms)

    def _request_kyocera_cancel(self) -> None:
        self._kyocera_cancel_requested = True
        if self._kyocera_worker is not None:
            self._kyocera_worker.cancel()
        self.kyocera_progress_status.setText("Отмена операции и остановка процесса...")
        self.cancel_kyocera_btn.setEnabled(False)
        self.preview.appendPlainText("Запрошена отмена операции Kyocera.")

    def _set_kyocera_running(self, running: bool, status: str, progress: int) -> None:
        self.kyocera_progress_frame.setVisible(True)
        self.kyocera_progress_status.setText(status)
        self.kyocera_progress_bar.setValue(progress)
        self.add_kyocera_btn.setEnabled(not running)
        self.preview_btn.setEnabled(not running)
        self.delete_printer_btn.setEnabled(not running)
        self.table.setEnabled(not running)
        self.cancel_kyocera_btn.setVisible(running)
        self.cancel_kyocera_btn.setEnabled(running)

    def _clear_kyocera_worker(self) -> None:
        self._kyocera_thread = None
        self._kyocera_worker = None
        self._kyocera_device = None
        self._kyocera_entry = None
        self._kyocera_cancel_requested = False

    def _offer_scan_folder_creation(self, entry: PrinterAddressBookEntry) -> None:
        if scan_folder_exists(entry.scan_path):
            self.preview.appendPlainText(f"\nПапка scan доступна: {entry.scan_path}")
            return

        self.preview.appendPlainText(f"\nПапка scan не найдена: {entry.scan_path}")
        self.context.audit.log(
            "scan_folder_check",
            object_type="user_folder",
            object_name=entry.scan_path,
            result="WARNING",
            message="После добавления записи Kyocera папка scan не найдена",
        )
        question = (
            "Запись в адресной книге Kyocera добавлена, но папка scan не найдена.\n\n"
            f"{entry.scan_path}\n\n"
            "Создать папку и назначить права?\n"
            "Пользователь и Domain Admins: полный доступ.\n"
            f"{self.context.config.scan_account}: изменение.\n\n"
            "После подтверждения потребуется учетная запись Domain Admins. "
            "Фактическое создание на UNC выполняется правами текущего Windows-пользователя."
        )
        if QMessageBox.question(self, "Папка scan отсутствует", question) != QMessageBox.Yes:
            self.preview.appendPlainText("Создание папки scan отменено пользователем.")
            self.context.audit.log(
                "scan_folder_create",
                object_type="user_folder",
                object_name=entry.scan_path,
                result="CANCELLED",
                message="Пользователь отказался создавать отсутствующую папку scan",
            )
            return

        if not request_privileged_operation_authorization(
            self.context,
            f"Создание папки scan и назначение прав: {entry.scan_path}",
            self,
        ):
            self.preview.appendPlainText("Папка scan не создана: проверка Domain Admins отменена или не пройдена.")
            self.context.audit.log(
                "scan_folder_create",
                object_type="user_folder",
                object_name=entry.scan_path,
                result="CANCELLED",
                message="Проверка Domain Admins не пройдена",
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = provision_scan_folder(entry, self.context.config)
        except Exception as exc:
            message = (
                f"Не удалось создать папку scan:\n{entry.scan_path}\n\n{exc}\n\n"
                "Проверьте доступ текущего Windows-пользователя к сетевому пути."
            )
            self.preview.appendPlainText(f"Ошибка создания папки scan: {exc}")
            self.context.audit.log(
                "scan_folder_create",
                object_type="user_folder",
                object_name=entry.scan_path,
                result="ERROR",
                message=str(exc),
            )
            QMessageBox.critical(self, "Папка scan", message)
            return
        finally:
            QApplication.restoreOverrideCursor()

        failed_acl = [item for item in result.acl_results if item.returncode != 0]
        if failed_acl:
            details = "\n".join(
                (item.stderr or item.stdout or " ".join(item.command)).strip()
                for item in failed_acl
            )
            self.preview.appendPlainText(
                f"Папка scan создана, но права применены с ошибками:\n{details}"
            )
            self.context.audit.log(
                "scan_folder_create",
                object_type="user_folder",
                object_name=str(result.path),
                result="WARNING",
                message=details,
            )
            QMessageBox.warning(
                self,
                "Папка scan",
                f"Папка создана, но права применены с ошибками:\n{result.path}\n\n{details}",
            )
            return

        self.preview.appendPlainText(f"Папка scan создана, права назначены: {result.path}")
        self.context.audit.log(
            "scan_folder_create",
            object_type="user_folder",
            object_name=str(result.path),
            result="SUCCESS",
            message="Папка scan создана после добавления записи Kyocera",
        )
        QMessageBox.information(
            self,
            "Папка scan",
            f"Папка создана и права назначены:\n{result.path}",
        )

    def _selected_device(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.devices):
            return None
        return self.devices[row]

    def _entry_from_form(self) -> PrinterAddressBookEntry:
        full_name = self.full_name.text().strip()
        login = self.login.text().strip()
        email = self.email.text().strip()
        if not full_name:
            raise ValueError("Укажите ФИО.")
        if not login:
            raise ValueError("Укажите login.")
        if not email:
            raise ValueError("Укажите email.")
        root = self.context.config.userfolder_root.rstrip("\\/")
        return PrinterAddressBookEntry(
            full_name=full_name,
            login=login,
            email=email,
            scan_path=rf"{root}\{login}\scan",
            smb_login=self.context.config.scan_account,
        )


def printer_identity_from_full_name(
    full_name: str,
    email_domain: str = DEFAULT_PRINTER_EMAIL_DOMAIN,
) -> tuple[str, str]:
    last_name, first_name, middle_name = parse_full_name(full_name)
    candidates = build_login_candidates(last_name, first_name, middle_name)
    login = candidates[0] if candidates else ""
    email = f"{login}@{email_domain.strip()}" if login and email_domain.strip() else ""
    return login, email


def merge_printer_devices_with_sources(
    shared_devices: list[PrinterDevice],
    local_devices: list[PrinterDevice],
) -> tuple[list[PrinterDevice], list[str]]:
    devices: list[PrinterDevice] = []
    sources: list[str] = []
    seen_hosts: set[str] = set()
    for source, source_devices in (("shared", shared_devices), ("local", local_devices)):
        for device in source_devices:
            host_key = device.host.strip().lower()
            if host_key and host_key in seen_hosts:
                continue
            if host_key:
                seen_hosts.add(host_key)
            devices.append(device)
            sources.append(source)
    return devices, sources


def kyocera_line_for_preview(line: str) -> str | None:
    """Возвращает строку для нижнего окна, убирая техническую диагностику прошивки."""
    source = (line or "").strip()
    if not source:
        return None

    if source.startswith("[ERROR]") or source.startswith("ОШИБКА:"):
        return source

    text = source.removeprefix("[KYOCERA]").strip()
    lowered = text.casefold()

    replacements = [
        ("get add page -> http 200", "[KYOCERA] Форма нового контакта открыта."),
        ("get addressbook -> http 200", "[KYOCERA] Адресная книга доступна."),
        ("post add contact -> http 200", "[KYOCERA] Принтер подтвердил сохранение контакта."),
        (
            "model формы добавления контакта не найден",
            "[KYOCERA] У этой прошивки нет отдельного model-файла, использую совместимый режим.",
        ),
    ]
    for marker, replacement in replacements:
        if marker in lowered:
            return replacement

    match = re.search(r"свободный номер вычислен по списку:\s*(\d{3})", text, flags=re.I)
    if match:
        return f"[KYOCERA] Свободный номер контакта: {match.group(1)}."

    hidden_markers = (
        "get add_model_candidate",
        "кандидат model не открылся",
        "get addressbook_number_probe",
        "ответ сохранён:",
        "текст сохранён:",
        "payload сохранён:",
        "cookies после post login",
        "post login url:",
        "отправляю логин как",
        "подготовительный get /",
        "get / не выполнен, продолжаю",
        "get addressbook list for discovery",
        "не удалось получить /js/jssrc/model/basic/addrbook_addr.model.htm",
        "не удалось получить /basic/addrbook_addr.htm",
        "hidden value",
        "add page url:",
        "post action формы:",
        "скрытых/служебных полей формы:",
    )
    if any(marker in lowered for marker in hidden_markers):
        return None

    return source


def kyocera_progress_from_output(line: str) -> tuple[int | None, str]:
    text = line.removeprefix("[KYOCERA]").strip()
    lowered = text.casefold()
    stages = [
        ("первичная проверка доступности", 5, "Проверяю доступность принтера по TCP 80/443..."),
        ("принтер доступен по tcp", 6, "Сетевое подключение к принтеру доступно."),
        ("определяю рабочий url", 7, "Определяю HTTP/HTTPS адрес принтера..."),
        ("проверка сертификата", 9, "Принимаю локальный сертификат Command Center RX..."),
        ("совместимый tls-режим", 10, "Включаю совместимость со старым TLS устройства..."),
        ("рабочий url принтера", 12, "Соединение с принтером установлено."),
        ("проверяю готовность принтера", 18, "Проверяю готовность устройства..."),
        ("принтер готов", 24, "Принтер готов к работе."),
        ("подготовительный get", 30, "Открываю Command Center RX..."),
        ("отправляю логин", 38, "Выполняю вход администратора..."),
        ("авторизация подтверждена", 47, "Авторизация подтверждена."),
        ("открываю список адресной книги", 55, "Читаю адресную книгу и тип прошивки..."),
        ("открываю страницу добавления контакта", 63, "Открываю форму нового контакта..."),
        ("номер для контакта", 70, "Свободный номер контакта определен."),
        ("отправляю контакт", 78, "Передаю контакт и SMB-параметры..."),
        ("ответ на post добавления контакта не получен", 86, "Ответ POST потерян, проверяю адресную книгу без повтора..."),
        ("post не повторяю", 86, "Проверяю результат без повторной отправки POST..."),
        ("принтер принял запись адресной книги", 92, "Принтер принял запись адресной книги."),
        ("post добавления контакта принят", 92, "Принтер принял новый контакт."),
        (
            "проверку списка после успешного post не запускаю",
            96,
            "Запись принята, завершаю без лишней проверки списка.",
        ),
        ("проверяю список адресной книги", 93, "Проверяю созданную запись..."),
        ("контакт найден", 98, "Контакт найден в адресной книге."),
        ("контакт найден после неоднозначного ответа", 98, "Контакт найден после проверки адресной книги."),
        ("готово", 100, "Операция успешно завершена."),
    ]
    for marker, progress, status in stages:
        if marker in lowered:
            return progress, status
    return None, text
