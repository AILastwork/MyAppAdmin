from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.glpi import (
    DEFAULT_GLPI_BASE_URL,
    GlpiComputer,
    GlpiSearchResult,
    GlpiWebClient,
    normalize_base_url,
    search_computers,
)
from app.ui.context import PageContext
from app.ui.widgets import Card, OperationLog, button, page_title


class GlpiLoadWorker(QObject):
    status = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, base_url: str, username: str, password: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            self.status.emit("Подключаюсь к GLPI...")
            client = GlpiWebClient(self.base_url)
            self.status.emit("Выполняю вход в GLPI...")
            client.login(self.username, self.password)
            self.status.emit("Загружаю список компьютеров...")
            computers = client.load_computers(on_status=self.status.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(computers)


class GlpiPage(QWidget):
    COLUMNS = [
        "ПК",
        "Пользователь",
        "IP",
        "MAC",
        "Модель",
        "CPU",
        "RAM",
        "Диск",
        "ОС",
        "Версия ОС",
        "Last boot",
        "Изменён",
        "Serial",
        "Причина",
    ]

    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.computers: list[GlpiComputer] = []
        self.current_results: list[GlpiSearchResult] = []
        self._load_thread: QThread | None = None
        self._load_worker: GlpiLoadWorker | None = None
        self.table_expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("GLPI"))

        self.connection_card = self._build_connection_card()
        layout.addWidget(self.connection_card)

        self.page_splitter = QSplitter(Qt.Vertical)
        self.page_splitter.setChildrenCollapsible(False)
        self.page_splitter.addWidget(self._build_results_card())
        self.log = OperationLog()
        self.log.setMinimumHeight(90)
        self.page_splitter.addWidget(self.log)
        self.page_splitter.setStretchFactor(0, 7)
        self.page_splitter.setStretchFactor(1, 1)
        self.page_splitter.setSizes([760, 110])
        layout.addWidget(self.page_splitter, 1)

    def _build_connection_card(self) -> QWidget:
        card = Card("Загрузка компьютеров из GLPI")
        form = QFormLayout()

        self.base_url = QLineEdit(getattr(self.context.config, "glpi_base_url", DEFAULT_GLPI_BASE_URL))
        self.base_url.setPlaceholderText(DEFAULT_GLPI_BASE_URL)
        form.addRow("GLPI URL", self.base_url)

        self.username = QLineEdit(_default_glpi_username())
        self.username.setPlaceholderText("a.nikitin")
        form.addRow("Логин GLPI", self.username)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Пароль GLPI")
        self.password.returnPressed.connect(self.load_from_glpi)
        form.addRow("Пароль GLPI", self.password)
        card.layout.addLayout(form)

        row = QHBoxLayout()
        self.load_btn = button("Загрузить из GLPI", primary=True)
        self.load_btn.clicked.connect(self.load_from_glpi)
        self.open_btn = button("Открыть выбранный в GLPI")
        self.open_btn.clicked.connect(self.open_selected_in_glpi)
        self.open_btn.setEnabled(False)
        row.addWidget(self.load_btn)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        card.layout.addLayout(row)

        self.progress_frame = QFrame()
        self.progress_frame.setProperty("role", "mailProgress")
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        self.progress_status = QLabel("Ожидание загрузки")
        self.progress_status.setObjectName("ProgressStatus")
        self.progress_status.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_status)
        progress_layout.addWidget(self.progress_bar)
        self.progress_frame.setVisible(False)
        card.layout.addWidget(self.progress_frame)

        note = QLabel(
            "GLPI API не используется: приложение входит в веб-интерфейс, читает список "
            "компьютеров и ищет по локально загруженной копии. Пароль не сохраняется."
        )
        note.setWordWrap(True)
        card.layout.addWidget(note)
        return card

    def _build_results_card(self) -> QWidget:
        card = Card("Поиск рабочего места")
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("login, ФИО, имя+фамилия, WRK-112, IP, MAC или серийный номер")
        self.query.returnPressed.connect(self.search_loaded)
        self.search_btn = button("Найти", primary=True)
        self.search_btn.clicked.connect(self.search_loaded)
        self.show_all_btn = button("Показать всё")
        self.show_all_btn.clicked.connect(self.show_all_loaded)
        self.expand_btn = button("Развернуть таблицу")
        self.expand_btn.clicked.connect(self.toggle_table_expanded)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_btn)
        search_row.addWidget(self.show_all_btn)
        search_row.addWidget(self.expand_btn)
        card.layout.addLayout(search_row)

        self.status = QLabel("Сначала загрузите список из GLPI.")
        self.status.setWordWrap(True)
        card.layout.addWidget(self.status)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 230)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 280)
        self.table.setColumnWidth(6, 80)
        self.table.setColumnWidth(8, 100)
        self.table.itemSelectionChanged.connect(self.show_selected_details)
        card.layout.addWidget(self.table, 1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        self.details.setPlaceholderText("Выберите компьютер в таблице, чтобы увидеть красивую карточку.")
        card.layout.addWidget(self.details)
        return card

    def load_from_glpi(self, _checked: bool = False) -> None:
        if self._load_thread and self._load_thread.isRunning():
            return

        base_url = normalize_base_url(self.base_url.text())
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, "GLPI", "Введите логин и пароль GLPI.")
            return

        self.base_url.setText(base_url)
        if getattr(self.context.config, "glpi_base_url", "") != base_url:
            self.context.config.glpi_base_url = base_url
            self.context.config.save(self.context.config_path)

        self.progress_frame.setVisible(True)
        self.progress_status.setText("Подключаюсь к GLPI...")
        self.load_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.details.clear()
        self.status.setText("Загружаю свежий список компьютеров из GLPI...")
        self.log.add("INFO", "GLPI", f"Старт загрузки: {base_url}")

        self._load_thread = QThread(self)
        self._load_worker = GlpiLoadWorker(base_url, username, password)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.status.connect(self._handle_load_status)
        self._load_worker.finished.connect(self._handle_load_finished)
        self._load_worker.failed.connect(self._handle_load_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._clear_load_worker)
        self._load_thread.start()

    def _handle_load_status(self, message: str) -> None:
        self.progress_status.setText(message)
        self.status.setText(message)

    def _handle_load_finished(self, computers: object) -> None:
        self.computers = list(computers) if isinstance(computers, list) else []
        self.progress_frame.setVisible(False)
        self.load_btn.setEnabled(True)
        self.password.clear()
        self.log.add("SUCCESS", "GLPI", f"Загружено компьютеров: {len(self.computers)}")
        self.context.audit.log(
            "glpi_load",
            object_type="glpi",
            result="SUCCESS",
            message=f"Загружено компьютеров: {len(self.computers)}",
        )
        if self.query.text().strip():
            self.search_loaded()
        else:
            self.show_all_loaded()

    def _handle_load_failed(self, message: str) -> None:
        self.progress_frame.setVisible(False)
        self.load_btn.setEnabled(True)
        self.status.setText("GLPI загрузка завершилась ошибкой.")
        self.log.add("ERROR", "GLPI", message)
        self.context.audit.log("glpi_load", object_type="glpi", result="ERROR", message=message)
        QMessageBox.critical(self, "GLPI", message)

    def _clear_load_worker(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def search_loaded(self, _checked: bool = False) -> None:
        if not self.computers:
            QMessageBox.information(self, "GLPI", "Сначала нажмите «Загрузить из GLPI».")
            return

        query = self.query.text().strip()
        results = search_computers(self.computers, query)
        self._set_results(results)
        self.status.setText(
            f"Найдено: {len(results)} из {len(self.computers)}. "
            f"Запрос: {query or 'весь список'}."
        )
        self.log.add("INFO", "GLPI", f"Поиск: {query or '<весь список>'}; найдено {len(results)}")
        self.context.audit.log("glpi_search", object_type="glpi", object_name=query, message=f"Найдено: {len(results)}")

    def show_all_loaded(self, _checked: bool = False) -> None:
        if not self.computers:
            self.status.setText("Сначала загрузите список из GLPI.")
            return
        results = [GlpiSearchResult(computer, 1, "весь загруженный список") for computer in self.computers]
        self._set_results(results)
        self.status.setText(f"Показан весь загруженный список: {len(results)} компьютеров.")

    def _set_results(self, results: list[GlpiSearchResult]) -> None:
        self.current_results = results
        self.table.setRowCount(0)
        for result in results:
            self._append_result(result)
        self.open_btn.setEnabled(bool(results))
        if results:
            self.table.selectRow(0)
        else:
            self.details.setPlainText("Ничего не найдено. Попробуйте login, ФИО, имя ПК, IP, MAC или серийный номер.")

    def _append_result(self, result: GlpiSearchResult) -> None:
        computer = result.computer
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            computer.name,
            computer.contact,
            computer.display_ip,
            computer.mac,
            computer.model,
            computer.processor,
            computer.memory,
            computer.disk,
            computer.os_name,
            computer.os_version,
            computer.last_boot,
            computer.modified,
            computer.serial,
            result.reason,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.table.setItem(row, column, item)

    def show_selected_details(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_results):
            return
        self.details.setPlainText(format_computer_details(self.current_results[row]))

    def open_selected_in_glpi(self, _checked: bool = False) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_results):
            return
        url = self.current_results[row].computer.url
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def toggle_table_expanded(self, _checked: bool = False) -> None:
        self.table_expanded = not self.table_expanded
        self.connection_card.setVisible(not self.table_expanded)
        self.details.setVisible(not self.table_expanded)
        self.log.setVisible(not self.table_expanded)
        self.expand_btn.setText("Свернуть таблицу" if self.table_expanded else "Развернуть таблицу")
        if self.table_expanded:
            self.page_splitter.setSizes([1000, 0])
            self.status.setText(
                f"Расширенный режим таблицы. Загружено компьютеров: {len(self.computers)}."
            )
        elif self.computers:
            self.status.setText(f"Загружено компьютеров: {len(self.computers)}.")


def format_computer_details(result: GlpiSearchResult) -> str:
    computer = result.computer
    lines = [
        f"ПК: {computer.name or '<без имени>'}",
        f"Пользователь: {computer.contact or 'не указан'}",
        "",
        "Сеть",
        f"  IP: {computer.display_ip or 'не указан'}",
        f"  MAC: {computer.mac or 'не указан'}",
        "",
        "Железо",
        f"  Модель: {' '.join(part for part in [computer.manufacturer, computer.model] if part) or 'не указана'}",
        f"  Тип: {computer.type or 'не указан'}",
        f"  Серийный номер: {computer.serial or 'не указан'}",
        f"  CPU: {computer.processor or 'не указан'}",
        f"  RAM: {computer.memory or 'не указана'} ({computer.memory_type or 'тип не указан'})",
        f"  Диск: {computer.disk or 'не указан'}",
        "",
        "ПО и инвентаризация",
        f"  ОС: {' '.join(part for part in [computer.os_name, computer.os_version] if part) or 'не указана'}",
        f"  Антивирус: {computer.antivirus or 'не указан'}",
        f"  Last boot: {computer.last_boot or 'не указан'}",
        f"  Последнее изменение GLPI: {computer.modified or 'не указано'}",
        "",
        f"Почему найдено: {result.reason}",
        f"GLPI ID: {computer.glpi_id}",
        f"Ссылка: {computer.url}",
    ]
    return "\n".join(lines)


def _default_glpi_username() -> str:
    return getpass.getuser()
