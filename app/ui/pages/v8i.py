from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QAbstractItemView,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import v8i
from app.services.v8i import list_template_profiles
from app.ui.context import PageContext
from app.ui.widgets import Card, OperationLog, button, page_title


class V8iPage(QWidget):
    COLUMNS = ["№", "", "Название базы", "Connect", "ClientConnectionSpeed", "App/Version"]

    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self._bases: list[v8i.V8iBase] = []
        self._template_bases: list[v8i.V8iBase] = []
        self._updating_table = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("1C / V8i"))

        content_splitter = QSplitter(Qt.Vertical)
        editor_splitter = QSplitter(Qt.Horizontal)

        card = Card("Файл ibases.v8i")
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(r"\\osnova.local\fs\IBASE\login\ibases.v8i")
        self.path_edit.setToolTip(r"Пример: \\osnova.local\fs\IBASE\i.ivanov\ibases.v8i")
        browse_btn = button("Выбрать")
        browse_btn.clicked.connect(self.browse)
        load_btn = button("Загрузить", primary=True)
        load_btn.clicked.connect(self.load_file)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(load_btn)
        card.layout.addLayout(path_row)

        action_row = QHBoxLayout()
        for text, handler in [
            ("Выбрать все", self.check_all),
            ("Снять все", self.uncheck_all),
            ("Добавить базу", self.add_base),
            ("Удалить отмеченные", self.delete_selected),
            ("Сохранить", self.save_file),
            ("Скопировать шаблон", self.copy_template),
            ("Создать 1CEStart.cfg", self.create_start_cfg),
        ]:
            btn = button(text, primary=text == "Сохранить")
            btn.clicked.connect(handler)
            action_row.addWidget(btn)
        action_row.addStretch(1)
        card.layout.addLayout(action_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Поиск"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Название базы, сервер, Ref или часть Connect")
        self.search_edit.textChanged.connect(self._apply_current_filter)
        select_found_btn = button("Отметить найденные")
        select_found_btn.clicked.connect(self.check_visible)
        unselect_found_btn = button("Снять найденные")
        unselect_found_btn.clicked.connect(self.uncheck_visible)
        delete_found_btn = button("Удалить найденные", danger=True)
        delete_found_btn.clicked.connect(self.delete_visible)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(select_found_btn)
        search_row.addWidget(unselect_found_btn)
        search_row.addWidget(delete_found_btn)
        card.layout.addLayout(search_row)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(1, 46)
        self.table.setColumnWidth(2, 260)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._handle_item_changed)
        card.layout.addWidget(self.table, 1)
        editor_splitter.addWidget(card)
        editor_splitter.addWidget(self._build_template_card())
        editor_splitter.setSizes([980, 420])

        self.log = OperationLog()
        self.log.setMinimumHeight(150)
        content_splitter.addWidget(editor_splitter)
        content_splitter.addWidget(self.log)
        content_splitter.setSizes([720, 160])
        layout.addWidget(content_splitter, 1)
        self.refresh_templates()

    def _build_template_card(self) -> QWidget:
        card = Card("Добавить базы из шаблона")

        profile_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.currentTextChanged.connect(self.load_selected_template)
        refresh_btn = button("Обновить")
        refresh_btn.clicked.connect(self.refresh_templates)
        profile_row.addWidget(self.template_combo, 1)
        profile_row.addWidget(refresh_btn)
        card.layout.addLayout(profile_row)

        self.template_search = QLineEdit()
        self.template_search.setPlaceholderText("Поиск базы в выбранном шаблоне")
        self.template_search.textChanged.connect(self._apply_template_filter)
        card.layout.addWidget(self.template_search)

        self.template_list = QListWidget()
        card.layout.addWidget(self.template_list, 1)

        template_actions = QHBoxLayout()
        mark_visible_btn = button("Отметить")
        mark_visible_btn.clicked.connect(lambda _checked=False: self._set_template_visible_checked(True))
        clear_visible_btn = button("Снять")
        clear_visible_btn.clicked.connect(lambda _checked=False: self._set_template_visible_checked(False))
        add_selected_btn = button("Добавить отмеченные", primary=True)
        add_selected_btn.clicked.connect(self.add_selected_from_template)
        template_actions.addWidget(mark_visible_btn)
        template_actions.addWidget(clear_visible_btn)
        template_actions.addWidget(add_selected_btn)
        template_actions.addStretch(1)
        card.layout.addLayout(template_actions)
        return card

    def browse(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Выбрать ibases.v8i", "", "V8i (*.v8i);;Все файлы (*.*)")
        if filename:
            self.path_edit.setText(filename)

    def load_file(self) -> None:
        try:
            path = self._current_path()
            self._bases = v8i.parse_v8i(path)
        except Exception as exc:
            self._show_error("Загрузка V8i", exc)
            return
        self._populate_table()
        self.log.add("INFO", "Загрузка V8i", f"Загружено баз: {len(self._bases)}")
        self.context.audit.log("v8i_load", object_type="v8i", object_name=str(path), message=f"Загружено баз: {len(self._bases)}")

    def save_file(self) -> None:
        try:
            path = self._current_path()
            bases = self._bases_from_table(only_checked=True)
            if not bases:
                QMessageBox.warning(self, "Сохранение V8i", "Отметьте хотя бы одну базу для сохранения.")
                return
            v8i.write_v8i(bases, path)
        except Exception as exc:
            self._show_error("Сохранение V8i", exc)
            return
        self._bases = bases
        self._populate_table()
        self.log.add("INFO", "Сохранение V8i", str(path))
        self.context.audit.log("v8i_save", object_type="v8i", object_name=str(path), result="SUCCESS", message="Файл сохранён")

    def add_base(self) -> None:
        self._bases = self._bases_from_table(only_checked=False)
        self._bases.append(v8i.V8iBase("Новая база", {"Connect": 'Srvr="1C-SRV01";Ref="NewBase";'}))
        self._populate_table()
        self.log.add("INFO", "Редактор V8i", "Добавлена строка")

    def check_all(self) -> None:
        self._set_all_checked(True)

    def uncheck_all(self) -> None:
        self._set_all_checked(False)

    def delete_selected(self) -> None:
        rows = [row for row in range(self.table.rowCount()) if self._row_checked(row)]
        if not rows:
            QMessageBox.information(self, "V8i", "Отметьте строки галочками для удаления.")
            return
        if QMessageBox.question(
            self,
            "Удалить строки",
            f"Удалить отмеченные строки из файла?\n\nКоличество: {len(rows)}",
        ) != QMessageBox.Yes:
            return
        self._bases = self._bases_from_table(only_checked=False)
        rows.sort(reverse=True)
        for row in rows:
            self.table.removeRow(row)
            self._bases.pop(row)
        self._renumber_rows()
        self._apply_current_filter()
        self.log.add("INFO", "Редактор V8i", f"Удалено строк: {len(rows)}")

    def copy_template(self) -> None:
        try:
            path = self._current_path()
            profiles = list_template_profiles(self.context.config.template_dir)
            if profiles:
                selected, ok = QInputDialog.getItem(
                    self,
                    "Выбор шаблона V8i",
                    "Шаблон",
                    [profile.name for profile in profiles],
                    0,
                    False,
                )
                if not ok or not selected:
                    return
                template = Path(self.context.config.template_dir) / selected
            else:
                template = self.context.config.template_path()

            overwrite = False
            if path.exists():
                answer = QMessageBox.question(
                    self,
                    "Шаблон V8i",
                    f"Файл уже существует:\n{path}\n\nПерезаписать его шаблоном?",
                )
                if answer != QMessageBox.Yes:
                    self.log.add("INFO", "Шаблон V8i", "Копирование отменено, файл уже существует")
                    return
                overwrite = True
            copied = v8i.copy_template_v8i(template, path, overwrite=overwrite)
            self.log.add("INFO", "Шаблон V8i", "Шаблон скопирован" if copied else "Файл уже существует")
            self.load_file()
        except Exception as exc:
            self._show_error("Шаблон V8i", exc)

    def create_start_cfg(self) -> None:
        try:
            ibases_path = self._current_path()
            cfg_path = ibases_path.parent / "1CEStart.cfg"
            v8i.create_1cestart_cfg(cfg_path, ibases_path, overwrite=True)
        except Exception as exc:
            self._show_error("1CEStart.cfg", exc)
            return
        self.log.add("INFO", "1CEStart.cfg", str(cfg_path))
        self.context.audit.log("create_1cestart_cfg", object_type="v8i", object_name=str(cfg_path), result="SUCCESS")

    def refresh_templates(self) -> None:
        selected = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        profiles = list_template_profiles(self.context.config.template_dir)
        for profile in profiles:
            self.template_combo.addItem(profile.name)

        if not profiles:
            self.template_combo.blockSignals(False)
            self._template_bases = []
            self.template_list.clear()
            self.log.add("INFO", "Шаблоны V8i", "Шаблоны не найдены")
            return

        index = 0
        if selected:
            selected_index = self.template_combo.findText(selected, Qt.MatchExactly)
            if selected_index >= 0:
                index = selected_index
        self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)
        self.load_selected_template(self.template_combo.currentText())

    def load_selected_template(self, name: str) -> None:
        if not name:
            self._template_bases = []
            self.template_list.clear()
            return
        path = Path(self.context.config.template_dir) / name
        try:
            self._template_bases = v8i.parse_v8i(path)
        except Exception as exc:
            self._template_bases = []
            self.template_list.clear()
            self.log.add("ERROR", "Шаблон V8i", str(exc))
            return
        self._populate_template_list()
        self.log.add("INFO", "Шаблон V8i", f"{name}: баз {len(self._template_bases)}")

    def add_selected_from_template(self) -> None:
        selected_bases = self._selected_template_bases()
        if not selected_bases:
            QMessageBox.information(self, "Шаблон V8i", "Отметьте базы в шаблоне.")
            return

        self._bases = self._bases_from_table(only_checked=False)
        existing_names = {base.name.strip().lower() for base in self._bases}
        added = 0
        skipped = 0
        for base in selected_bases:
            if base.name.strip().lower() in existing_names:
                skipped += 1
                continue
            self._bases.append(v8i.V8iBase(base.name, base.fields.copy()))
            existing_names.add(base.name.strip().lower())
            added += 1

        self._populate_table()
        self.log.add("INFO", "Шаблон V8i", f"Добавлено баз: {added}; пропущено совпадений: {skipped}")

    def _current_path(self) -> Path:
        text = self.path_edit.text().strip()
        path = v8i.normalize_ibases_path(text)
        if str(path) != text:
            self.path_edit.setText(str(path))
        return path

    def _show_error(self, title: str, exc: Exception) -> None:
        message = str(exc) or exc.__class__.__name__
        QMessageBox.warning(self, title, message)
        self.log.add("ERROR", title, message)

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

            values = [base.name, base.fields.get("Connect", ""), base.fields.get("ClientConnectionSpeed", ""), base.version()]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setToolTip("Поле App или Version")
                self.table.setItem(row, column + 2, item)
            self._style_row(row)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._updating_table = False
        self._apply_current_filter()

    def _populate_template_list(self) -> None:
        self.template_list.blockSignals(True)
        self.template_list.setUpdatesEnabled(False)
        self.template_list.clear()
        for index, base in enumerate(self._template_bases):
            details = " | ".join(part for part in [base.name, base.server(), base.ref()] if part)
            item = QListWidgetItem(details or base.name or "Unnamed")
            item.setData(Qt.UserRole, index)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Unchecked)
            self.template_list.addItem(item)
        self.template_list.setUpdatesEnabled(True)
        self.template_list.blockSignals(False)
        self._apply_template_filter()

    def _apply_current_filter(self, _text: str = "") -> None:
        query = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""
        for row in range(self.table.rowCount()):
            haystack = " ".join(self._item_text(row, column) for column in range(2, self.table.columnCount())).lower()
            self.table.setRowHidden(row, bool(query and query not in haystack))

    def _apply_template_filter(self, _text: str = "") -> None:
        query = self.template_search.text().strip().lower() if hasattr(self, "template_search") else ""
        for index in range(self.template_list.count()):
            item = self.template_list.item(index)
            self.template_list.setRowHidden(index, bool(query and query not in item.text().lower()))

    def check_visible(self) -> None:
        self._set_visible_checked(True)

    def uncheck_visible(self) -> None:
        self._set_visible_checked(False)

    def delete_visible(self) -> None:
        rows = self._visible_rows()
        if not rows:
            QMessageBox.information(self, "V8i", "Нет найденных строк для удаления.")
            return
        answer = QMessageBox.question(self, "Удалить найденные базы", f"Удалить видимые строки после фильтра: {len(rows)}?")
        if answer != QMessageBox.Yes:
            return

        current = self._bases_from_table(only_checked=False)
        delete_set = set(rows)
        self._bases = [base for row, base in enumerate(current) if row not in delete_set]
        self._populate_table()
        self.log.add("INFO", "Редактор V8i", f"Удалено найденных строк: {len(rows)}")

    def _set_visible_checked(self, checked: bool) -> None:
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for row in self._visible_rows():
            item = self.table.item(row, 1)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self._style_row(row)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

    def _visible_rows(self) -> list[int]:
        return [row for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)]

    def _set_template_visible_checked(self, checked: bool) -> None:
        for index in range(self.template_list.count()):
            if self.template_list.isRowHidden(index):
                continue
            self.template_list.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _selected_template_bases(self) -> list[v8i.V8iBase]:
        bases: list[v8i.V8iBase] = []
        for index in range(self.template_list.count()):
            item = self.template_list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            source_index = item.data(Qt.UserRole)
            if isinstance(source_index, int) and 0 <= source_index < len(self._template_bases):
                bases.append(self._template_bases[source_index])
        return bases

    def _bases_from_table(self, only_checked: bool = False) -> list[v8i.V8iBase]:
        bases: list[v8i.V8iBase] = []
        for row in range(self.table.rowCount()):
            if only_checked and not self._row_checked(row):
                continue
            original = self._bases[row].fields.copy() if row < len(self._bases) else {}
            name = self._item_text(row, 2) or "Unnamed"
            original["Connect"] = self._item_text(row, 3)
            original["ClientConnectionSpeed"] = self._item_text(row, 4)
            version = self._item_text(row, 5)
            if version:
                original["App"] = version
            bases.append(v8i.V8iBase(name, original))
        return bases

    def _handle_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table:
            return
        if item.column() == 1:
            self._style_row(item.row())
        elif item.column() in {2, 3, 4, 5}:
            self._apply_current_filter()

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

    def _row_checked(self, row: int) -> bool:
        item = self.table.item(row, 1)
        return bool(item and item.checkState() == Qt.Checked)

    def _style_row(self, row: int) -> None:
        checked = self._row_checked(row)
        foreground = "#dff3ef" if checked else "#8798a5"
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item:
                item.setForeground(QColor(foreground))

    def _renumber_rows(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setText(str(row + 1))

    def _item_text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""
