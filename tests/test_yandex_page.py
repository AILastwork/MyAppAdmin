from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from app.audit import AuditLogger
from app.config import AppConfig
from app.ui.context import PageContext
from app.services.yandex360 import YandexOrg, YandexUser
from app.ui.pages.yandex import YandexPage


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_yandex_users_table_can_expand_and_restore(tmp_path):
    _application()
    context = PageContext(
        AppConfig(yandex_token_file=str(tmp_path / "missing-token.txt")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = YandexPage(context)

    assert "Последняя активность" not in page.COLUMNS
    assert "Не используется, дней" not in page.COLUMNS
    assert page.users_splitter.orientation() == Qt.Vertical
    assert page.page_splitter.orientation() == Qt.Vertical
    assert page.log.minimumHeight() == 80
    assert page.create_panel.isHidden()
    assert page.expand_users_btn.text() == "Показать форму"
    button_texts = {widget.text() for widget in page.findChildren(QPushButton)}
    assert "Сохранить в Excel" in button_texts
    assert not page.export_btn.isEnabled()

    page.toggle_users_table_expanded()

    assert not page.create_panel.isHidden()
    assert page.expand_users_btn.text() == "Развернуть список"

    page.toggle_users_table_expanded()

    assert page.create_panel.isHidden()
    assert page.expand_users_btn.text() == "Показать форму"


def test_yandex_users_can_be_exported_to_excel_from_page(monkeypatch, tmp_path):
    _application()
    context = PageContext(
        AppConfig(yandex_token_file=str(tmp_path / "missing-token.txt")),
        AuditLogger(tmp_path / "audit.db"),
        tmp_path / "config.json",
    )
    page = YandexPage(context)
    org = YandexOrg("mkd", "OSNOVA", "mkd-osnova.ru", "42", "1", True)
    page.orgs = [org]
    page.org_combo.clear()
    page.org_combo.addItem("mkd-osnova.ru", org.key)
    page.users = [
        YandexUser(
            id="100",
            nickname="e.morozova",
            email="e.morozova@mkd-osnova.ru",
            display_name="Морозова Екатерина Андреевна",
            is_enabled=True,
        )
    ]
    target = tmp_path / "export.xlsx"
    monkeypatch.setattr(
        "app.ui.pages.yandex.QFileDialog.getSaveFileName",
        lambda *_args: (str(target), "Книга Excel (*.xlsx)"),
    )
    monkeypatch.setattr("app.ui.pages.yandex.QMessageBox.information", lambda *_args: None)

    page.export_users_to_excel()

    assert target.exists()
