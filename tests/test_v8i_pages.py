from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.audit import AuditLogger
from app.config import AppConfig
from app.services.v8i import V8iBase
from app.ui.context import PageContext
from app.ui.pages.templates import TemplatesPage
from app.ui.pages.v8i import V8iPage


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _context(tmp_path) -> PageContext:
    config = AppConfig(
        template_dir=str(tmp_path / "templates"),
        audit_db=str(tmp_path / "audit.db"),
    )
    return PageContext(config, AuditLogger(config.audit_db), tmp_path / "config.json")


def _sample_bases() -> list[V8iBase]:
    return [
        V8iBase("Первая", {"Connect": 'Srvr="srv";Ref="one";'}),
        V8iBase("Вторая", {"Connect": 'Srvr="srv";Ref="two";'}),
        V8iBase("Третья", {"Connect": 'Srvr="srv";Ref="three";'}),
    ]


def test_templates_delete_uses_checkboxes_not_blue_selection(monkeypatch, tmp_path):
    _application()
    page = TemplatesPage(_context(tmp_path))
    page._bases = _sample_bases()
    page._populate_table()
    page._set_all_checked(False)
    page.table.item(1, 1).setCheckState(Qt.Checked)
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

    page.delete_selected_rows()

    assert [base.name for base in page._bases] == ["Первая", "Третья"]


def test_v8i_delete_uses_checkboxes_not_blue_selection(monkeypatch, tmp_path):
    _application()
    page = V8iPage(_context(tmp_path))
    page._bases = _sample_bases()
    page._populate_table()
    page._set_all_checked(False)
    page.table.item(1, 1).setCheckState(Qt.Checked)
    page.table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

    page.delete_selected()

    assert [base.name for base in page._bases] == ["Первая", "Третья"]
