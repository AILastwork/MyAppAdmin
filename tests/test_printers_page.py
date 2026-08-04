from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from app.audit import AuditLogger
from app.config import AppConfig
from app.services.printers.base import PrinterAddressBookEntry, add_printer_device
from app.ui.context import PageContext
from app.ui.pages.printers import (
    PrintersPage,
    kyocera_line_for_preview,
    kyocera_progress_from_output,
    printer_identity_from_full_name,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_printer_can_be_added_from_ip_field(tmp_path, monkeypatch):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.information", lambda *_args: None)
    page.printer_ip.setText("192.168.20.25")
    page.printer_name.setText("KM1E33BC")
    page.printer_model.setText("ECOSYS MA4500x")

    page.add_printer_by_ip()

    assert page.table.rowCount() == 1
    assert page.devices[0].host == "192.168.20.25"
    assert page.devices[0].name == "KM1E33BC"
    assert page.devices[0].model == "ECOSYS MA4500x"
    assert page.table.currentRow() == 0
    assert page.local_printer_config_file == tmp_path / "printers.local.json"
    assert page.local_printer_config_file.exists()


def test_printer_page_combines_shared_and_local_devices(tmp_path):
    _application()
    shared_path = tmp_path / "shared-printers.json"
    shared_path.write_text(
        '{"devices":[{"name":"Общий","vendor":"Kyocera","model":"","host":"192.168.1.10"}]}',
        encoding="utf-8",
    )
    context = PageContext(
        AppConfig(printer_config_file=str(shared_path)),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    add_printer_device(page.local_printer_config_file, "192.168.1.20", name="Локальный")

    page.refresh()

    assert [(device.name, device.host) for device in page.devices] == [
        ("Общий", "192.168.1.10"),
        ("Локальный", "192.168.1.20"),
    ]


def test_printer_page_removes_local_device(tmp_path, monkeypatch):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "missing.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    add_printer_device(page.local_printer_config_file, "192.168.1.20", name="Локальный")
    page.refresh()
    page.table.selectRow(0)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.information", lambda *_args: None)

    page.remove_selected_printer()

    assert page.table.rowCount() == 0
    assert "удален" in page.preview.toPlainText().lower()
    assert page.local_printer_config_file.exists()
    assert "192.168.1.20" not in page.local_printer_config_file.read_text(encoding="utf-8")


def test_printer_page_removes_shared_device_after_confirmation(tmp_path, monkeypatch):
    _application()
    shared_path = tmp_path / "shared-printers.json"
    shared_path.write_text(
        '{"devices":[{"name":"Общий","vendor":"Kyocera","model":"","host":"192.168.1.10"}]}',
        encoding="utf-8",
    )
    context = PageContext(
        AppConfig(printer_config_file=str(shared_path)),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    page.table.selectRow(0)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.information", lambda *_args: None)

    page.remove_selected_printer()

    assert page.table.rowCount() == 0
    assert "192.168.1.10" not in shared_path.read_text(encoding="utf-8")


def test_printer_config_can_be_selected_from_page(tmp_path, monkeypatch):
    _application()
    selected_path = tmp_path / "selected-printers.json"
    selected_path.write_text(
        '{"devices":[{"name":"Выбранный","vendor":"Kyocera","model":"","host":"192.168.5.10"}]}',
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "missing.json")),
        AuditLogger(tmp_path / "audit.db"),
        config_path,
    )
    page = PrintersPage(context)
    monkeypatch.setattr(
        "app.ui.pages.printers.QFileDialog.getOpenFileName",
        lambda *_args: (str(selected_path), "JSON (*.json)"),
    )
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.information", lambda *_args: None)

    page.select_printer_config()

    assert context.config.printer_config_file == str(selected_path)
    assert page.devices[0].host == "192.168.5.10"
    assert str(selected_path) in page.printer_config_path.text()
    assert config_path.exists()


def test_printer_identity_is_generated_from_full_name():
    assert printer_identity_from_full_name("Морозова Екатерина Андреевна") == (
        "e.morozova",
        "e.morozova@mkd-osnova.ru",
    )


def test_printer_page_autofills_login_and_email_but_preserves_manual_values(tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)

    page.full_name.setText("Морозова Екатерина Андреевна")

    assert page.login.text() == "e.morozova"
    assert page.email.text() == "e.morozova@mkd-osnova.ru"

    page.login.setText("custom.login")
    page.sync_email_from_login("custom.login")
    page.email.setText("manual@example.ru")
    page.mark_email_as_manual()
    page.full_name.setText("Иванов Иван Иванович")
    page.autofill_identity()

    assert page.login.text() == "custom.login"
    assert page.email.text() == "manual@example.ru"


def test_printer_page_shows_verified_kyocera_models(tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    labels = [label.text() for label in page.findChildren(QLabel)]

    assert any(
        "ECOSYS M3145dn" in text
        and "ECOSYS M3540idn" in text
        and "ECOSYS MA4500x" in text
        for text in labels
    )


def test_kyocera_progress_follows_live_script_stages(tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)

    page._set_kyocera_running(True, "Старт", 3)
    page._handle_kyocera_output("[KYOCERA] Авторизация подтверждена.")
    assert page.kyocera_progress_bar.value() == 47
    assert "Авторизация" in page.kyocera_progress_status.text()

    page._handle_kyocera_output("[KYOCERA] Отправляю контакт с номером 015...")
    assert page.kyocera_progress_bar.value() == 78
    assert "Передаю контакт" in page.kyocera_progress_status.text()
    assert "Отправляю контакт" in page.preview.toPlainText()

    page._handle_kyocera_output("[KYOCERA] Принтер принял запись адресной книги.")
    assert page.kyocera_progress_bar.value() == 92
    assert "принял" in page.kyocera_progress_status.text().lower()

    page._handle_kyocera_output(
        "[KYOCERA] Проверку списка после успешного POST не запускаю: Kyocera уже приняла запись."
    )
    assert page.kyocera_progress_bar.value() == 96
    assert "лишней проверки" in page.kyocera_progress_status.text().lower()

    assert kyocera_progress_from_output("[KYOCERA] ГОТОВО.")[0] == 100


def test_kyocera_preview_hides_low_level_firmware_probe_lines(tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)

    page._set_kyocera_running(True, "Старт", 3)
    page._handle_kyocera_output("[KYOCERA] GET add page -> HTTP 200")
    page._handle_kyocera_output(
        "[KYOCERA] GET add_model_candidate_1: http://printer/model.htm -> HTTP 404"
    )
    page._handle_kyocera_output(
        "[KYOCERA] Кандидат model не открылся: http://printer/model.htm; "
        "('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))"
    )
    page._handle_kyocera_output("[KYOCERA] Ответ сохранён: kyocera_add_model_candidate_1_error.html")
    page._handle_kyocera_output(
        "[KYOCERA] Model формы добавления контакта не найден. Будет использован fallback без model."
    )
    page._handle_kyocera_output(
        "[KYOCERA] Свободный номер вычислен по списку: 011. Занятые: [1, 2, 3]..."
    )

    text = page.preview.toPlainText()

    assert "Форма нового контакта открыта" in text
    assert "совместимый режим" in text
    assert "Свободный номер контакта: 011" in text
    assert "add_model_candidate" not in text
    assert "RemoteDisconnected" not in text
    assert "kyocera_add_model_candidate" not in text


def test_kyocera_line_for_preview_keeps_real_errors():
    assert kyocera_line_for_preview("[ERROR] real failure") == "[ERROR] real failure"


def test_active_kyocera_operation_can_be_cancelled_and_waited(tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)

    class FakeWorker:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class FakeThread:
        def __init__(self):
            self.interrupted = False
            self.quit_requested = False

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def quit(self):
            self.quit_requested = True

        def wait(self, wait_ms):
            return wait_ms == 5000

    worker = FakeWorker()
    thread = FakeThread()
    page._kyocera_worker = worker
    page._kyocera_thread = thread

    assert page.cancel_active_operation()
    assert worker.cancelled
    assert thread.interrupted
    assert thread.quit_requested
    assert "отмена" in page.kyocera_progress_status.text().lower()


def test_cancel_race_does_not_start_scan_folder_provisioning(monkeypatch, tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    page._kyocera_cancel_requested = True
    page._kyocera_entry = PrinterAddressBookEntry(
        "Иванов Иван",
        "i.ivanov",
        "i.ivanov@mkd-osnova.ru",
        str(tmp_path / "scan"),
    )
    monkeypatch.setattr(
        page,
        "_offer_scan_folder_creation",
        lambda *_args: pytest.fail("Создание папки не должно запускаться после запроса отмены"),
    )

    page._handle_kyocera_finished(object())

    assert "не откатываются" in page.preview.toPlainText()


def test_missing_scan_folder_is_created_only_after_confirmation_and_admin_auth(monkeypatch, tmp_path):
    _application()
    context = PageContext(
        AppConfig(
            printer_config_file=str(tmp_path / "printers.json"),
            userfolder_root=str(tmp_path / "users"),
        ),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    entry = PrinterAddressBookEntry(
        full_name="Иванов Иван Иванович",
        login="i.ivanov",
        email="i.ivanov@mkd-osnova.ru",
        scan_path=str(tmp_path / "users" / "i.ivanov" / "scan"),
    )
    provisioned: list[str] = []
    monkeypatch.setattr("app.ui.pages.printers.scan_folder_exists", lambda _path: False)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(
        "app.ui.pages.printers.request_privileged_operation_authorization",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "app.ui.pages.printers.provision_scan_folder",
        lambda value, _config: provisioned.append(value.scan_path)
        or SimpleNamespace(path=value.scan_path, acl_results=[]),
    )
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.information", lambda *_args: None)

    page._offer_scan_folder_creation(entry)

    assert provisioned == [entry.scan_path]
    assert "права назначены" in page.preview.toPlainText()


def test_missing_scan_folder_is_not_created_when_admin_auth_fails(monkeypatch, tmp_path):
    _application()
    context = PageContext(
        AppConfig(printer_config_file=str(tmp_path / "printers.json")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = PrintersPage(context)
    entry = PrinterAddressBookEntry("Иванов Иван", "i.ivanov", "i.ivanov@mkd-osnova.ru", str(tmp_path / "scan"))
    monkeypatch.setattr("app.ui.pages.printers.scan_folder_exists", lambda _path: False)
    monkeypatch.setattr("app.ui.pages.printers.QMessageBox.question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(
        "app.ui.pages.printers.request_privileged_operation_authorization",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "app.ui.pages.printers.provision_scan_folder",
        lambda *_args, **_kwargs: pytest.fail("Папка не должна создаваться без проверки Domain Admins"),
    )

    page._offer_scan_folder_creation(entry)

    assert "не создана" in page.preview.toPlainText()
