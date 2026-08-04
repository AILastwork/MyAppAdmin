from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.audit import AuditLogger
from app.config import AppConfig
from app.ui.context import PageContext
from app.ui.main_window import MainWindow
from app.ui.pages.create_user import CreateUserPage
from app.ui.pages.settings import SettingsPage


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        userfolder_root=str(tmp_path / "users"),
        user_scan_root=str(tmp_path / "scan"),
        user_1c_root=str(tmp_path / "onec"),
        template_dir=str(tmp_path / "templates"),
        yandex_token_file=str(tmp_path / "missing-yandex.txt"),
        printer_config_file=str(tmp_path / "missing-printers.json"),
        audit_db=str(tmp_path / "audit.db"),
    )


def test_create_user_page_has_no_manual_acl_retry_button(tmp_path):
    _application()
    config = _config(tmp_path)
    context = PageContext(config, AuditLogger(config.audit_db), tmp_path / "config.json")

    page = CreateUserPage(context)
    button_texts = {widget.text() for widget in page.findChildren(QPushButton)}

    assert "Папки / повторить ACL" not in button_texts
    assert "Создать пользователя" in button_texts


def test_settings_page_is_hidden_for_non_domain_admin(monkeypatch, tmp_path):
    _application()
    config = _config(tmp_path)
    monkeypatch.setattr("app.ui.main_window.is_current_user_domain_admin", lambda: False)

    window = MainWindow(config, AuditLogger(config.audit_db), tmp_path / "config.json")
    sidebar_titles = {window.sidebar.item(index).text() for index in range(window.sidebar.count())}

    assert "Настройки" not in sidebar_titles
    assert "Описание программы" in sidebar_titles
    window.close()


def test_settings_have_no_denied_groups_field(monkeypatch, tmp_path):
    _application()
    config = _config(tmp_path)
    context = PageContext(config, AuditLogger(config.audit_db), tmp_path / "config.json")
    monkeypatch.setattr("app.ui.pages.settings.is_current_user_domain_admin", lambda: True)

    page = SettingsPage(context)

    assert "denied_groups" not in page.inputs
