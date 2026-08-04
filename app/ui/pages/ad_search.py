from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.ad_directory import (
    AdGroup,
    AdOrganizationalUnit,
    AdUser,
    change_user_password,
    generate_password as generate_ad_password,
    list_group_members,
    list_ou_members,
    search_groups,
    search_organizational_units,
    search_users,
    set_user_enabled,
)
from app.ui.ad_admin_auth import request_privileged_operation_authorization
from app.ui.context import PageContext
from app.ui.widgets import Card, button, page_title


@dataclass(slots=True)
class AdSearchRow:
    kind: str
    user: AdUser | None = None
    group: AdGroup | None = None
    ou: AdOrganizationalUnit | None = None
    members: list[AdUser] | None = field(default=None)


class AdSearchPage(QWidget):
    COLUMNS = ["Тип", "Login", "ФИО", "Почта", "Телефон", "Отдел", "Должность", "Статус", "Создан", "Последняя активность", "OU"]
    NEW_DEFAULT_COLUMNS = ["Тип", "Создан", "Последняя активность"]

    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.rows: list[AdSearchRow] = []
        self._columns_migrated = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("Поиск AD"))

        card = Card("Поиск сотрудника, группы или OU")
        form = QFormLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("i.ivanov, Иванов Иван, IT Admins или OU=Users")
        self.query.returnPressed.connect(self.search)
        form.addRow("Login / ФИО / email / группа / OU", self.query)
        card.layout.addLayout(form)

        actions = QHBoxLayout()
        search_btn = button("Найти в AD", primary=True)
        search_btn.clicked.connect(self.search)
        columns_btn = button("Вид")
        columns_btn.clicked.connect(self.configure_columns)
        lock_btn = button("Заблокировать учетку", danger=True)
        lock_btn.clicked.connect(lambda _checked=False: self.set_selected_user_enabled(False))
        unlock_btn = button("Снять блокировку")
        unlock_btn.clicked.connect(lambda _checked=False: self.set_selected_user_enabled(True))
        password_btn = button("Сменить пароль")
        password_btn.clicked.connect(self.change_selected_user_password)
        actions.addWidget(search_btn)
        actions.addWidget(columns_btn)
        actions.addWidget(lock_btn)
        actions.addWidget(unlock_btn)
        actions.addWidget(password_btn)
        actions.addStretch(1)
        card.layout.addLayout(actions)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(8, 150)
        self.table.setColumnWidth(9, 170)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Выберите пользователя, группу или OU. Для группы/OU здесь появится список участников.")
        self.table.currentCellChanged.connect(self.show_details)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setSizes([620, 260])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        card.layout.addWidget(splitter, 1)

        layout.addWidget(card, 1)
        self.apply_column_visibility()

    def search(self, _checked: bool = False) -> None:
        query = self.query.text().strip()
        self.details.clear()
        self.table.setRowCount(0)
        self.rows = []

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            users = search_users(self.context.config, query)
            groups = search_groups(self.context.config, query)
            ous = search_organizational_units(self.context.config, query)
        except Exception as exc:
            self.details.setPlainText(
                "\n".join(
                    [
                        "Поиск AD не выполнен.",
                        "",
                        str(exc),
                        "",
                        "Проверьте настройки: ad_ldap_server, ad_ldaps_port, ad_read_user, ad_read_password, base_dn.",
                    ]
                )
            )
            self.context.audit.log("ad_search", object_type="ad_directory", object_name=query, result="ERROR", message=str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        for user in users:
            self._append_row(AdSearchRow("Пользователь", user=user))
        for group in groups:
            self._append_row(AdSearchRow("Группа", group=group))
        for ou in ous:
            self._append_row(AdSearchRow("OU", ou=ou))

        summary = f"Найдено: пользователей {len(users)}, групп {len(groups)}, OU {len(ous)}"
        self.details.setPlainText(summary)
        self.context.audit.log("ad_search", object_type="ad_directory", object_name=query, result="SUCCESS", message=summary)

    def show_details(self, row: int, _column: int, _previous_row: int, _previous_column: int) -> None:
        if row < 0 or row >= len(self.rows):
            return
        item = self.rows[row]
        if item.user:
            self.details.setPlainText(self._user_details(item.user))
            return
        if item.group:
            self._show_group_details(item)
            return
        if item.ou:
            self._show_ou_details(item)

    def set_selected_user_enabled(self, enabled: bool) -> None:
        user = self._selected_user()
        if not user:
            QMessageBox.information(self, "Поиск AD", "Выберите строку пользователя AD.")
            return

        action = "снять блокировку и включить" if enabled else "заблокировать и отключить"
        if not request_privileged_operation_authorization(self.context, f"AD: {action} учетную запись {user.login}", self):
            self.context.audit.log("ad_set_enabled", object_type="ad_user", object_name=user.login, result="CANCELLED")
            return

        question = f"{action.capitalize()} учетную запись AD?\n\nLogin: {user.login}\nФИО: {user.name}\nDN: {user.dn}"
        if QMessageBox.question(self, "AD учетная запись", question) != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            set_user_enabled(self.context.config, user.dn, enabled)
        except Exception as exc:
            self.context.audit.log("ad_set_enabled", object_type="ad_user", object_name=user.login, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "AD учетная запись", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        user.disabled = not enabled
        self._refresh_selected_user_status(user)
        status = "активен" if enabled else "отключен"
        self.details.setPlainText(self._user_details(user))
        self.context.audit.log("ad_set_enabled", object_type="ad_user", object_name=user.login, result="SUCCESS", message=status)
        QMessageBox.information(self, "AD учетная запись", f"{user.login}: {status}")

    def change_selected_user_password(self, _checked: bool = False) -> None:
        user = self._selected_user()
        if not user:
            QMessageBox.information(self, "Поиск AD", "Выберите строку пользователя AD.")
            return

        if not request_privileged_operation_authorization(self.context, f"AD: смена пароля учетной записи {user.login}", self):
            self.context.audit.log("ad_change_password", object_type="ad_user", object_name=user.login, result="CANCELLED")
            return

        dialog = PasswordChangeDialog(user.login, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        question = f"Сменить пароль учетной записи AD?\n\nLogin: {user.login}\nФИО: {user.name}\nDN: {user.dn}"
        if QMessageBox.question(self, "Смена пароля AD", question) != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            change_user_password(
                self.context.config,
                user.dn,
                dialog.password_text(),
                change_at_logon=dialog.change_at_logon(),
            )
        except Exception as exc:
            self.context.audit.log("ad_change_password", object_type="ad_user", object_name=user.login, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "Смена пароля AD", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.context.audit.log("ad_change_password", object_type="ad_user", object_name=user.login, result="SUCCESS")
        QMessageBox.information(self, "Смена пароля AD", f"Пароль изменен для {user.login}")

    def _show_group_details(self, row: AdSearchRow) -> None:
        group = row.group
        if not group:
            return
        try:
            members = self._members_for_row(row, group.dn, is_group=True)
        except Exception as exc:
            self.details.setPlainText(f"Не удалось загрузить членов группы.\n\n{exc}")
            self.context.audit.log("ad_group_members", object_type="ad_group", object_name=group.name, result="ERROR", message=str(exc))
            return

        lines = [
            f"Группа: {group.name}",
            f"Login: {group.account_name}",
            f"Создана: {group.created}",
            f"Описание: {group.description}",
            f"DN: {group.dn}",
            "",
            f"Члены группы: {len(members)}",
        ]
        lines.extend(self._member_lines(members))
        self.details.setPlainText("\n".join(lines))
        self.context.audit.log("ad_group_members", object_type="ad_group", object_name=group.name, result="SUCCESS", message=f"Членов: {len(members)}")

    def _show_ou_details(self, row: AdSearchRow) -> None:
        ou = row.ou
        if not ou:
            return
        try:
            members = self._members_for_row(row, ou.dn, is_group=False)
        except Exception as exc:
            self.details.setPlainText(f"Не удалось загрузить пользователей OU.\n\n{exc}")
            self.context.audit.log("ad_ou_members", object_type="ad_ou", object_name=ou.dn, result="ERROR", message=str(exc))
            return

        lines = [
            f"OU: {ou.name}",
            f"Создана: {ou.created}",
            f"Описание: {ou.description}",
            f"DN: {ou.dn}",
            "",
            f"Пользователи в OU: {len(members)}",
        ]
        lines.extend(self._member_lines(members))
        self.details.setPlainText("\n".join(lines))
        self.context.audit.log("ad_ou_members", object_type="ad_ou", object_name=ou.dn, result="SUCCESS", message=f"Пользователей: {len(members)}")

    def _members_for_row(self, row: AdSearchRow, dn: str, *, is_group: bool) -> list[AdUser]:
        if row.members is not None:
            return row.members
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            row.members = list_group_members(self.context.config, dn) if is_group else list_ou_members(self.context.config, dn)
        finally:
            QApplication.restoreOverrideCursor()
        return row.members

    def _append_row(self, item: AdSearchRow) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.rows.append(item)
        for column, value in enumerate(self._row_values(item)):
            table_item = QTableWidgetItem(value)
            table_item.setFlags(table_item.flags() ^ Qt.ItemIsEditable)
            if column in (0, 7):
                table_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, column, table_item)

    def _row_values(self, item: AdSearchRow) -> list[str]:
        if item.user:
            user = item.user
            return [
                item.kind,
                user.login,
                user.name,
                user.mail,
                user.phone,
                user.department,
                user.title,
                "отключен" if user.disabled else "активен",
                user.created,
                user.last_activity,
                user.ou,
            ]
        if item.group:
            group = item.group
            return [item.kind, group.account_name or group.name, group.description, "", "", "", "", "группа", group.created, "", group.dn]
        if item.ou:
            ou = item.ou
            return [item.kind, ou.name, ou.description, "", "", "", "", "OU", ou.created, "", ou.dn]
        return [""] * len(self.COLUMNS)

    def _selected_user(self) -> AdUser | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row].user

    def _refresh_selected_user_status(self, user: AdUser) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        status_column = self.COLUMNS.index("Статус")
        self.table.setItem(row, status_column, QTableWidgetItem("отключен" if user.disabled else "активен"))

    def _user_details(self, user: AdUser) -> str:
        lines = [
            f"Login: {user.login}",
            f"ФИО: {user.name}",
            f"UPN: {user.upn}",
            f"Почта: {user.mail}",
            f"Телефон: {user.phone}",
            f"Отдел: {user.department}",
            f"Должность: {user.title}",
            f"Компания: {user.company}",
            f"Офис: {user.office}",
            f"Руководитель: {user.manager}",
            f"Создан: {user.created}",
            f"Последняя активность: {user.last_activity}",
            f"Статус: {'отключен' if user.disabled else 'активен'}",
            f"DN: {user.dn}",
            "",
            "Группы:",
        ]
        lines.extend(f"- {group}" for group in user.groups)
        return "\n".join(lines)

    def _member_lines(self, members: list[AdUser]) -> list[str]:
        if not members:
            return ["- нет пользователей"]
        return [
            f"- {user.login} | {user.name} | {user.mail or 'без почты'} | {'отключен' if user.disabled else 'активен'} | последняя активность: {user.last_activity}"
            for user in members
        ]

    def configure_columns(self) -> None:
        dialog = ColumnPickerDialog(self.COLUMNS, self._visible_columns(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_columns()
        if not selected:
            selected = list(self.COLUMNS)
        self.context.config.ad_search_visible_columns = selected
        if self.context.on_config_changed:
            self.context.on_config_changed()
        self.apply_column_visibility()

    def apply_column_visibility(self) -> None:
        visible = set(self._visible_columns())
        for column, title in enumerate(self.COLUMNS):
            self.table.setColumnHidden(column, title not in visible)

    def _visible_columns(self) -> list[str]:
        configured = [column for column in self.context.config.ad_search_visible_columns if column in self.COLUMNS]
        if configured and not self._columns_migrated:
            self._columns_migrated = True
            for column in self.NEW_DEFAULT_COLUMNS:
                if column not in configured:
                    insert_at = 0 if column == "Тип" else len(configured)
                    configured.insert(insert_at, column)
        return configured or list(self.COLUMNS)


class PasswordChangeDialog(QDialog):
    def __init__(self, login: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Смена пароля AD")
        self.resize(460, 210)

        layout = QFormLayout(self)
        account = QLabel(login)
        account.setStyleSheet("font-weight: 700; color: #ffffff;")
        layout.addRow("Учетная запись", account)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Новый пароль")
        self.repeat = QLineEdit()
        self.repeat.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat.setPlaceholderText("Повторите новый пароль")

        password_row = QHBoxLayout()
        password_row.addWidget(self.password, 1)
        generate_btn = button("Сгенерировать")
        generate_btn.clicked.connect(self.generate_password)
        password_row.addWidget(generate_btn)
        password_widget = QWidget()
        password_widget.setLayout(password_row)

        self.must_change = QCheckBox("Потребовать смену пароля при первом входе")
        self.must_change.setChecked(True)
        layout.addRow("Пароль", password_widget)
        layout.addRow("Повтор", self.repeat)
        layout.addRow("", self.must_change)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def generate_password(self, _checked: bool = False) -> None:
        password = generate_ad_password(10)
        self.password.setText(password)
        self.repeat.setText(password)

    def accept(self) -> None:
        password = self.password.text().strip()
        repeat = self.repeat.text().strip()
        if not password:
            QMessageBox.warning(self, "Смена пароля AD", "Введите новый пароль.")
            return
        if password != repeat:
            QMessageBox.warning(self, "Смена пароля AD", "Пароли не совпадают.")
            return
        super().accept()

    def password_text(self) -> str:
        return self.password.text().strip()

    def change_at_logon(self) -> bool:
        return self.must_change.isChecked()


class ColumnPickerDialog(QDialog):
    def __init__(self, columns: list[str], visible_columns: list[str], parent: QWidget | None = None, title: str = "Вид") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 420)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        visible = set(visible_columns)
        for column in columns:
            item = QListWidgetItem(column)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if column in visible else Qt.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_columns(self) -> list[str]:
        result: list[str] = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                result.append(item.text())
        return result
