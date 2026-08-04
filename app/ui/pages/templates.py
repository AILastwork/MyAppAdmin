from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import v8i
from app.services.v8i import list_template_profiles, normalize_template_filename, rename_template_profile
from app.ui.context import PageContext
from app.ui.widgets import Card, button, page_title


class TemplatesPage(QWidget):
    COLUMNS = ["№", "", "Название базы", "Srvr", "Ref", "ClientConnectionSpeed", "App/Version", "Connect"]
    PREVIEW_FULL_LIMIT = 200

    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.current_path: Path | None = None
        self._bases: list[v8i.V8iBase] = []
        self._updating_table = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("Шаблоны баз 1C"))

        splitter = QSplitter()
        splitter.addWidget(self._build_profiles_card())
        splitter.addWidget(self._build_editor_card())
        splitter.setSizes([330, 980])
        layout.addWidget(splitter, 1)
        self.refresh()

    def _build_profiles_card(self) -> QWidget:
        card = Card("Профили")

        actions = QHBoxLayout()
        refresh_btn = button("Обновить")
        refresh_btn.clicked.connect(self.refresh)
        new_btn = button("Новый", primary=True)
        new_btn.clicked.connect(self.new_template)
        delete_btn = button("Удалить", danger=True)
        delete_btn.clicked.connect(self.delete_template)
        actions.addWidget(refresh_btn)
        actions.addWidget(new_btn)
        actions.addWidget(delete_btn)
        actions.addStretch(1)
        card.layout.addLayout(actions)

        self.list_widget = QListWidget()
        self.list_widget.currentTextChanged.connect(self.load_template)
        card.layout.addWidget(self.list_widget)
        return card

    def _build_editor_card(self) -> QWidget:
        card = Card("Редактор шаблона")

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Файл"))
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("default.v8i")
        self.filename.setToolTip(r"Имя файла шаблона, например default.v8i. Папка задается в настройках: template_dir.")
        file_row.addWidget(self.filename, 1)
        save_btn = button("Сохранить", primary=True)
        save_btn.clicked.connect(self.save_template)
        rename_btn = button("Переименовать")
        rename_btn.clicked.connect(self.rename_template)
        file_row.addWidget(save_btn)
        file_row.addWidget(rename_btn)
        card.layout.addLayout(file_row)

        action_row = QHBoxLayout()
        for text, handler in [
            ("Выбрать все", self.check_all),
            ("Снять все", self.uncheck_all),
            ("Добавить базу", self.add_base),
            ("Удалить отмеченные", self.delete_selected_rows),
        ]:
            btn = button(text)
            btn.clicked.connect(handler)
            action_row.addWidget(btn)
        action_row.addStretch(1)
        card.layout.addLayout(action_row)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 46)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 160)
        self.table.setColumnWidth(5, 150)
        self.table.setColumnWidth(6, 120)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._handle_item_changed)
        card.layout.addWidget(self.table, 1)

        card.layout.addWidget(QLabel("Предпросмотр сохраняемого файла"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(150)
        card.layout.addWidget(self.preview)
        return card

    def refresh(self) -> None:
        selected = self.filename.text().strip() or (self.current_path.name if self.current_path else "")
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for profile in list_template_profiles(self.context.config.template_dir):
            self.list_widget.addItem(profile.name)
        self.list_widget.blockSignals(False)

        if selected:
            matches = self.list_widget.findItems(selected, Qt.MatchExactly)
            if matches:
                self.list_widget.setCurrentItem(matches[0])
                return
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        elif not self.filename.text().strip():
            self.new_template()

    def new_template(self) -> None:
        self.current_path = None
        self.filename.setText(self._next_template_name())
        self._bases = []
        self._populate_table()
        self._update_preview()

    def load_template(self, name: str) -> None:
        if not name:
            return
        path = Path(self.context.config.template_dir) / name
        self.current_path = path
        self.filename.setText(name)
        try:
            self._bases = v8i.parse_v8i(path)
            self._populate_table()
            self._update_preview()
        except Exception as exc:
            self._bases = []
            self._populate_table()
            self.preview.setPlainText(str(exc))

    def add_base(self) -> None:
        self._bases = self._bases_from_table(only_checked=False)
        self._bases.append(v8i.V8iBase("Новая база", {"Connect": 'Srvr="1C-SRV01";Ref="NewBase";', "ClientConnectionSpeed": "Normal"}))
        self._populate_table()
        self._update_preview()

    def delete_selected_rows(self) -> None:
        rows = [row for row in range(self.table.rowCount()) if self._row_checked(row)]
        if not rows:
            QMessageBox.information(self, "Шаблон баз", "Отметьте строки галочками для удаления.")
            return
        if QMessageBox.question(
            self,
            "Удалить строки",
            f"Удалить отмеченные строки из шаблона?\n\nКоличество: {len(rows)}",
        ) != QMessageBox.Yes:
            return
        self._bases = self._bases_from_table(only_checked=False)
        rows.sort(reverse=True)
        for row in rows:
            self.table.removeRow(row)
            self._bases.pop(row)
        self._renumber_rows()
        self._update_preview()

    def check_all(self) -> None:
        self._set_all_checked(True)

    def uncheck_all(self) -> None:
        self._set_all_checked(False)

    def save_template(self) -> None:
        try:
            filename = self._normalized_filename()
            bases = self._bases_from_table(only_checked=True)
        except ValueError as exc:
            QMessageBox.warning(self, "Шаблон баз", str(exc))
            return

        if not bases:
            QMessageBox.warning(self, "Шаблон баз", "Отметьте хотя бы одну базу для сохранения.")
            return

        path = Path(self.context.config.template_dir) / filename
        if path.exists() and self.current_path != path:
            answer = QMessageBox.question(self, "Шаблон баз", f"Файл уже существует:\n{path}\n\nПерезаписать?")
            if answer != QMessageBox.Yes:
                return

        try:
            v8i.write_v8i(bases, path)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения шаблона", str(exc))
            return

        self.current_path = path
        self.filename.setText(path.name)
        self._bases = bases
        self.context.audit.log("v8i_template_save", object_type="v8i_template", object_name=str(path), result="SUCCESS", message=f"Баз в шаблоне: {len(bases)}")
        self.refresh()
        QMessageBox.information(self, "Шаблон баз", f"Шаблон сохранен:\n{path}")

    def delete_template(self) -> None:
        if not self.current_path or not self.current_path.exists():
            QMessageBox.information(self, "Шаблон баз", "Выберите существующий шаблон.")
            return
        answer = QMessageBox.question(self, "Удалить шаблон", f"Удалить файл шаблона?\n{self.current_path}")
        if answer != QMessageBox.Yes:
            return
        try:
            self.current_path.unlink()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка удаления шаблона", str(exc))
            return
        self.context.audit.log("v8i_template_delete", object_type="v8i_template", object_name=str(self.current_path), result="SUCCESS")
        self.current_path = None
        self.filename.clear()
        self._bases = []
        self.refresh()

    def rename_template(self) -> None:
        if not self.current_path or not self.current_path.exists():
            QMessageBox.information(self, "Шаблон баз", "Выберите существующий шаблон.")
            return
        try:
            new_name = normalize_template_filename(self.filename.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Переименовать шаблон", str(exc))
            return

        old_path = self.current_path
        if new_name == old_path.name:
            QMessageBox.information(self, "Переименовать шаблон", "Имя шаблона не изменилось.")
            return
        if QMessageBox.question(
            self,
            "Переименовать шаблон",
            f"Переименовать шаблон?\n\n{old_path.name}\n→ {new_name}",
        ) != QMessageBox.Yes:
            return

        try:
            new_path = rename_template_profile(old_path, new_name)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка переименования шаблона", str(exc))
            return

        self.current_path = new_path
        self.filename.setText(new_path.name)
        if self.context.config.default_1c_profile.casefold() == old_path.name.casefold():
            self.context.config.default_1c_profile = new_path.name
            if self.context.on_config_changed:
                self.context.on_config_changed()
        self.context.audit.log(
            "v8i_template_rename",
            object_type="v8i_template",
            object_name=str(new_path),
            result="SUCCESS",
            message=f"Переименован шаблон: {old_path.name} -> {new_path.name}",
        )
        self.refresh()
        QMessageBox.information(self, "Шаблон баз", f"Шаблон переименован:\n{new_path}")

    def _populate_table(self) -> None:
        self._updating_table = True
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._bases))
        for row, base in enumerate(self._bases):

            number = QTableWidgetItem(str(row + 1))
            number.setTextAlignment(Qt.AlignCenter)
            number.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, number)

            enabled = QTableWidgetItem()
            enabled.setCheckState(Qt.Checked)
            enabled.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            enabled.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, enabled)

            values = [
                base.name,
                base.server(),
                base.ref(),
                base.client(),
                base.version(),
                base.fields.get("Connect", ""),
            ]
            for column, value in enumerate(values, start=2):
                self.table.setItem(row, column, QTableWidgetItem(value))
            self._style_row(row)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._updating_table = False

    def _bases_from_table(self, only_checked: bool) -> list[v8i.V8iBase]:
        bases: list[v8i.V8iBase] = []
        for row in range(self.table.rowCount()):
            if only_checked and not self._row_checked(row):
                continue

            original = self._bases[row].fields.copy() if row < len(self._bases) else {}
            name = self._item_text(row, 2) or "Unnamed"
            server = self._item_text(row, 3)
            ref = self._item_text(row, 4)
            connect = self._item_text(row, 7)
            original["Connect"] = self._connect_from_parts(server, ref, connect)
            original["ClientConnectionSpeed"] = self._item_text(row, 5)

            version = self._item_text(row, 6)
            if version:
                original["App"] = version
                original.pop("Version", None)
            else:
                original.pop("App", None)
                original.pop("Version", None)

            bases.append(v8i.V8iBase(name, original))
        return bases

    def _handle_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table:
            return

        row = item.row()
        if item.column() == 1:
            self._style_row(row)
        elif item.column() in {3, 4}:
            self._sync_connect_from_parts(row)
        elif item.column() == 7:
            self._sync_parts_from_connect(row)
        self._update_preview()

    def _sync_connect_from_parts(self, row: int) -> None:
        connect_item = self.table.item(row, 7)
        if not connect_item:
            return
        connect = self._connect_from_parts(self._item_text(row, 3), self._item_text(row, 4), connect_item.text())
        self._updating_table = True
        connect_item.setText(connect)
        self._updating_table = False

    def _sync_parts_from_connect(self, row: int) -> None:
        connect = self._item_text(row, 7)
        base = v8i.V8iBase("", {"Connect": connect})
        self._updating_table = True
        for column, value in [(3, base.server()), (4, base.ref())]:
            item = self.table.item(row, column)
            if item:
                item.setText(value)
        self._updating_table = False

    def _update_preview(self) -> None:
        try:
            bases = self._bases_from_table(only_checked=True)
            if len(bases) > self.PREVIEW_FULL_LIMIT:
                sample = v8i.serialize_v8i(bases[:30])
                self.preview.setPlainText(
                    "\n".join(
                        [
                            f"Отмечено баз: {len(bases)}.",
                            "Полный предпросмотр отключен для больших шаблонов, чтобы интерфейс не подвисал.",
                            "При сохранении будут записаны все отмеченные базы.",
                            "",
                            "Первые 30 баз:",
                            sample,
                        ]
                    )
                )
            else:
                self.preview.setPlainText(v8i.serialize_v8i(bases))
        except Exception as exc:
            self.preview.setPlainText(str(exc))

    def _set_all_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self._style_row(row)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._update_preview()

    def _row_checked(self, row: int) -> bool:
        item = self.table.item(row, 1)
        return bool(item and item.checkState() == Qt.Checked)

    def _style_row(self, row: int) -> None:
        checked = self._row_checked(row)
        foreground = QColor("#dff3ef" if checked else "#8798a5")
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setForeground(foreground)

    def _renumber_rows(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setText(str(row + 1))

    def _normalized_filename(self) -> str:
        return normalize_template_filename(self.filename.text())

    def _next_template_name(self) -> str:
        directory = Path(self.context.config.template_dir)
        candidate = "default.v8i"
        if not (directory / candidate).exists():
            return candidate
        index = 1
        while True:
            candidate = f"template_{index}.v8i"
            if not (directory / candidate).exists():
                return candidate
            index += 1

    def _connect_from_parts(self, server: str, ref: str, current_connect: str) -> str:
        connect = current_connect.strip()
        connect = self._set_connect_value(connect, "Srvr", server.strip())
        connect = self._set_connect_value(connect, "Ref", ref.strip())
        return connect

    def _set_connect_value(self, connect: str, key: str, value: str) -> str:
        parts = [part.strip() for part in connect.split(";") if part.strip()]
        prefix = f"{key}="
        replacement = f'{key}="{value}"' if value else ""

        replaced = False
        result: list[str] = []
        for part in parts:
            if part.startswith(prefix):
                replaced = True
                if replacement:
                    result.append(replacement)
            else:
                result.append(part)

        if replacement and not replaced:
            result.append(replacement)
        return ";".join(result) + (";" if result else "")

    def _item_text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""
