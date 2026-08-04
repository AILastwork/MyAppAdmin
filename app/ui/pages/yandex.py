from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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

from app.services.ad_directory import build_login_candidates, generate_password as generate_ad_password, parse_full_name
from app.services.yandex360 import (
    YandexCreateUserRequest,
    YandexOrg,
    YandexUser,
    create_yandex_user,
    format_datetime,
    list_yandex_users,
    load_yandex_orgs,
    set_yandex_user_enabled,
)
from app.services.xlsx_export import export_yandex_users_xlsx
from app.ui.pages.ad_search import ColumnPickerDialog
from app.ui.ad_admin_auth import request_privileged_operation_authorization
from app.ui.context import PageContext
from app.ui.widgets import Card, OperationLog, button, page_title


class YandexUsersWorker(QObject):
    status = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, org: YandexOrg, query: str) -> None:
        super().__init__()
        self.org = org
        self.query = query

    def run(self) -> None:
        try:
            self.status.emit("Подключаюсь к Yandex 360 API...")
            users = list_yandex_users(self.org, query=self.query)
            self.status.emit("Готовлю таблицу пользователей...")
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(users)


class YandexPage(QWidget):
    COLUMNS = ["Email", "Login", "ФИО", "Статус", "Создана", "Изменена", "Статус изменен", "ID"]

    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.admin_authorized = False
        self.orgs: list[YandexOrg] = []
        self.users: list[YandexUser] = []
        self._load_thread: QThread | None = None
        self._load_worker: YandexUsersWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("Почта Yandex 360"))

        layout.addWidget(self._build_auth_card())
        self.page_splitter = QSplitter(Qt.Vertical)
        self.page_splitter.setChildrenCollapsible(False)
        self.page_splitter.addWidget(self._build_users_card())
        self.log = OperationLog()
        self.log.setMinimumHeight(80)
        self.page_splitter.addWidget(self.log)
        self.page_splitter.setStretchFactor(0, 6)
        self.page_splitter.setStretchFactor(1, 1)
        self.page_splitter.setSizes([720, 100])
        layout.addWidget(self.page_splitter, 1)
        self.refresh()

    def on_activate(self) -> None:
        if not self.admin_authorized:
            self.request_admin_auth()

    def _build_auth_card(self) -> QWidget:
        card = Card("Доступ к операциям Yandex 360")
        row = QHBoxLayout()
        self.auth_status = QLabel("Требуется проверка доменного администратора AD")
        auth_btn = button("Проверить AD-админа", primary=True)
        auth_btn.clicked.connect(self.request_admin_auth)
        row.addWidget(self.auth_status, 1)
        row.addWidget(auth_btn)
        card.layout.addLayout(row)
        return card

    def _build_users_card(self) -> QWidget:
        card = Card("Пользователи домена")

        org_row = QHBoxLayout()
        org_row.addWidget(QLabel("Организация"))
        self.org_combo = QComboBox()
        org_row.addWidget(self.org_combo, 1)
        self.refresh_orgs_btn = button("Обновить")
        self.refresh_orgs_btn.clicked.connect(self.refresh)
        org_row.addWidget(self.refresh_orgs_btn)
        card.layout.addLayout(org_row)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("email, login или часть ФИО")
        self.query.returnPressed.connect(self.load_users)
        self.load_btn = button("Загрузить пользователей", primary=True)
        self.load_btn.clicked.connect(self.load_users)
        view_btn = button("Вид")
        view_btn.clicked.connect(self.configure_columns)
        self.export_btn = button("Сохранить в Excel")
        self.export_btn.clicked.connect(self.export_users_to_excel)
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("Сохранить текущую загруженную выборку пользователей в файл .xlsx")
        self.expand_users_btn = button("Развернуть список")
        self.expand_users_btn.clicked.connect(self.toggle_users_table_expanded)
        block_btn = button("Заблокировать", danger=True)
        block_btn.clicked.connect(lambda _checked=False: self.set_selected_enabled(False))
        unblock_btn = button("Разблокировать")
        unblock_btn.clicked.connect(lambda _checked=False: self.set_selected_enabled(True))
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.load_btn)
        search_row.addWidget(view_btn)
        search_row.addWidget(self.export_btn)
        search_row.addWidget(self.expand_users_btn)
        search_row.addWidget(block_btn)
        search_row.addWidget(unblock_btn)
        card.layout.addLayout(search_row)

        self.progress_frame = QFrame()
        self.progress_frame.setProperty("role", "mailProgress")
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)
        progress_head = QHBoxLayout()
        self.progress_title = QLabel("Загрузка каталога Yandex 360")
        self.progress_title.setObjectName("ProgressTitle")
        self.progress_status = QLabel("Ожидание запроса")
        self.progress_status.setObjectName("ProgressStatus")
        progress_head.addWidget(self.progress_title)
        progress_head.addStretch(1)
        progress_head.addWidget(self.progress_status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        progress_layout.addLayout(progress_head)
        progress_layout.addWidget(self.progress_bar)
        self.progress_frame.setVisible(False)
        card.layout.addWidget(self.progress_frame)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(8, 150)
        self.table.setColumnWidth(9, 150)

        self.create_panel = QWidget()
        create_panel_layout = QHBoxLayout(self.create_panel)
        create_panel_layout.setContentsMargins(0, 0, 0, 0)
        create_panel_layout.setSpacing(12)
        create_controls = QWidget()
        create_controls_layout = QVBoxLayout(create_controls)
        create_controls_layout.setContentsMargins(0, 0, 0, 0)
        create_controls_layout.setSpacing(8)
        create_form = QFormLayout()
        self.create_full_name = QLineEdit()
        self.create_full_name.setPlaceholderText("Хайруллова Инна Генадьевна")
        self.create_full_name.editingFinished.connect(self.suggest_create_login)
        self.create_login = QLineEdit()
        self.create_login.setPlaceholderText("i.khairullova")
        create_login_row = QWidget()
        create_login_layout = QHBoxLayout(create_login_row)
        create_login_layout.setContentsMargins(0, 0, 0, 0)
        create_login_layout.setSpacing(8)
        suggest_login_btn = button("Подобрать")
        suggest_login_btn.clicked.connect(self.suggest_create_login)
        create_login_layout.addWidget(self.create_login, 1)
        create_login_layout.addWidget(suggest_login_btn)
        self.create_position = QLineEdit()
        self.create_position.setPlaceholderText("Должность")
        self.create_password = QLineEdit()
        self.create_password.setPlaceholderText("10 символов: a/A/0/!@_")
        password_row = QHBoxLayout()
        password_row.addWidget(self.create_password, 1)
        generate_btn = button("Сгенерировать")
        generate_btn.clicked.connect(self.generate_create_password)
        password_row.addWidget(generate_btn)
        password_widget = QWidget()
        password_widget.setLayout(password_row)
        self.create_change_required = QCheckBox("Сменить пароль при первом входе")
        self.create_change_required.setChecked(True)
        create_form.addRow("ФИО", self.create_full_name)
        create_form.addRow("Login", create_login_row)
        create_form.addRow("Должность", self.create_position)
        create_form.addRow("Пароль", password_widget)
        create_form.addRow("", self.create_change_required)
        create_controls_layout.addLayout(create_form)

        create_row = QHBoxLayout()
        create_btn = button("Создать пользователя Yandex", primary=True)
        create_btn.clicked.connect(self.create_user)
        copy_message_btn = button("Скопировать письмо")
        copy_message_btn.clicked.connect(self.copy_mail_message)
        create_row.addWidget(create_btn)
        create_row.addWidget(copy_message_btn)
        create_row.addStretch(1)
        create_controls_layout.addLayout(create_row)
        create_controls_layout.addStretch(1)
        create_panel_layout.addWidget(create_controls, 3)

        self.mail_message = QPlainTextEdit()
        self.mail_message.setReadOnly(True)
        self.mail_message.setPlaceholderText("После заполнения ФИО/login/пароля здесь будет письмо по созданной почте.")
        self.mail_message.setMinimumHeight(120)
        create_panel_layout.addWidget(self.mail_message, 2)

        self.users_splitter = QSplitter(Qt.Vertical)
        self.users_splitter.setChildrenCollapsible(False)
        self.users_splitter.addWidget(self.table)
        self.users_splitter.addWidget(self.create_panel)
        self.users_splitter.setStretchFactor(0, 5)
        self.users_splitter.setStretchFactor(1, 1)
        self.users_splitter.setSizes([620, 170])
        self._users_splitter_sizes = [620, 170]
        self.create_panel.hide()
        self.expand_users_btn.setText("Показать форму")
        card.layout.addWidget(self.users_splitter, 1)
        return card

    def toggle_users_table_expanded(self, _checked: bool = False) -> None:
        if not self.create_panel.isHidden():
            sizes = self.users_splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._users_splitter_sizes = sizes
            self.create_panel.hide()
            self.expand_users_btn.setText("Показать форму")
            return

        self.create_panel.show()
        self.users_splitter.setSizes(self._users_splitter_sizes or [620, 170])
        self.expand_users_btn.setText("Развернуть список")

    def refresh(self) -> None:
        current_key = self.org_combo.currentData() if hasattr(self, "org_combo") else ""
        self.orgs = load_yandex_orgs(self.context.config.yandex_token_file)
        self.org_combo.clear()
        for org in self.orgs:
            title = " | ".join(part for part in [org.domain, org.name, f"org {org.org_id}"] if part)
            self.org_combo.addItem(title, org.key)
        if current_key:
            index = self.org_combo.findData(current_key)
            if index >= 0:
                self.org_combo.setCurrentIndex(index)
        self.context.audit.log("yandex_load_orgs", object_type="yandex360", message=f"Загружено организаций: {len(self.orgs)}")
        self.apply_column_visibility()

    def request_admin_auth(self, _checked: bool = False) -> bool:
        self.admin_authorized = request_privileged_operation_authorization(self.context, "Операции Yandex 360", self)
        if self.admin_authorized:
            self.auth_status.setText("Доменная учетная запись подтверждена. Операции Yandex 360 доступны.")
        else:
            self.auth_status.setText("Операции Yandex 360 заблокированы до проверки доменной учетной записи.")
        return self.admin_authorized

    def load_users(self, _checked: bool = False) -> None:
        if not self._ensure_authorized():
            return
        if self._load_thread and self._load_thread.isRunning():
            return
        org = self._current_org()
        if not org:
            QMessageBox.warning(self, "Почта Yandex", "Выберите организацию Yandex 360.")
            return

        self._set_loading(True, "Старт запроса...")
        query = self.query.text().strip()
        self._load_thread = QThread(self)
        self._load_worker = YandexUsersWorker(org, query)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.status.connect(self.progress_status.setText)
        self._load_worker.finished.connect(self._handle_users_loaded)
        self._load_worker.failed.connect(self._handle_users_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.finished.connect(self._clear_load_worker)
        self._load_thread.start()

    def _handle_users_loaded(self, users: object) -> None:
        self.users = list(users) if isinstance(users, list) else []
        self._set_loading(False, "Готово")
        self._populate_users_table()
        self.export_btn.setEnabled(bool(self.users))
        self.log.add("INFO", "Yandex users", f"Загружено пользователей: {len(self.users)}")
        self.context.audit.log("yandex_list_users", object_type="yandex360_user", result="SUCCESS", message=f"Загружено: {len(self.users)}")

    def _handle_users_failed(self, message: str) -> None:
        self.users = []
        self.export_btn.setEnabled(False)
        self._set_loading(False, "Ошибка загрузки")
        self.log.add("ERROR", "Yandex users", message)
        QMessageBox.warning(self, "Yandex users", message)

    def _clear_load_worker(self) -> None:
        self._load_thread = None
        self._load_worker = None

    def _set_loading(self, loading: bool, status: str) -> None:
        self.progress_status.setText(status)
        self.progress_frame.setVisible(loading)
        self.load_btn.setEnabled(not loading)
        self.refresh_orgs_btn.setEnabled(not loading)
        self.org_combo.setEnabled(not loading)
        self.query.setEnabled(not loading)

    def create_user(self, _checked: bool = False) -> None:
        if not self._ensure_authorized():
            return
        org = self._current_org()
        if not org:
            QMessageBox.warning(self, "Почта Yandex", "Выберите организацию Yandex 360.")
            return
        if not self.create_password.text().strip():
            self.generate_create_password()
        if not self.create_login.text().strip():
            self.suggest_create_login()
        last_name, first_name, middle_name = parse_full_name(self.create_full_name.text())
        if not self.create_login.text().strip() or not last_name or not first_name:
            QMessageBox.warning(self, "Почта Yandex", "Заполните ФИО и login.")
            return

        email = f"{self.create_login.text().strip()}@{org.domain}" if org.domain else self.create_login.text().strip()
        question = (
            "Создать пользователя Yandex 360?\n\n"
            f"Организация: {org.name or org.key}\n"
            f"Email: {email}\n"
            f"ФИО: {' '.join(part for part in [last_name, first_name, middle_name] if part)}"
        )
        if QMessageBox.question(self, "Создать пользователя Yandex", question) != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            user = create_yandex_user(
                org,
                YandexCreateUserRequest(
                    nickname=self.create_login.text().strip(),
                    password=self.create_password.text().strip(),
                    first_name=first_name,
                    last_name=last_name,
                    middle_name=middle_name,
                    position=self.create_position.text().strip(),
                    password_change_required=self.create_change_required.isChecked(),
                ),
            )
        except Exception as exc:
            self.log.add("ERROR", "Yandex create", str(exc))
            self.context.audit.log("yandex_create_user", object_type="yandex360_user", object_name=email, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "Создать пользователя Yandex", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.log.add("INFO", "Yandex create", f"Создан: {user.email or email}")
        self.context.audit.log("yandex_create_user", object_type="yandex360_user", object_name=user.email or email, result="SUCCESS")
        self.mail_message.setPlainText(self._mail_message(user.email or email))
        QApplication.clipboard().setText(self.mail_message.toPlainText())
        self.load_users()

    def suggest_create_login(self, _checked: bool = False) -> None:
        if self.create_login.text().strip():
            self.mail_message.setPlainText(self._mail_message())
            return
        last_name, first_name, middle_name = parse_full_name(self.create_full_name.text())
        candidates = build_login_candidates(last_name, first_name, middle_name)
        if not candidates:
            return
        selected = candidates[0]
        existing = {
            user.nickname.lower()
            for user in self.users
            if user.nickname
        }
        existing.update(
            user.email.split("@", 1)[0].lower()
            for user in self.users
            if user.email
        )
        for candidate in candidates:
            if candidate.lower() not in existing:
                selected = candidate
                break
        self.create_login.setText(selected)
        self.mail_message.setPlainText(self._mail_message())

    def copy_mail_message(self, _checked: bool = False) -> None:
        if not self.create_password.text().strip():
            self.generate_create_password()
        if not self.create_login.text().strip():
            self.suggest_create_login()
        message = self._mail_message()
        if not message:
            QMessageBox.warning(self, "Письмо Yandex", "Заполните ФИО, login и пароль.")
            return
        self.mail_message.setPlainText(message)
        QApplication.clipboard().setText(message)
        self.log.add("INFO", "Письмо Yandex", "Текст письма скопирован в буфер обмена")

    def configure_columns(self) -> None:
        dialog = ColumnPickerDialog(self.COLUMNS, self._visible_columns(), self, title="Вид Yandex")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_columns() or list(self.COLUMNS)
        self.context.config.yandex_visible_columns = selected
        if self.context.on_config_changed:
            self.context.on_config_changed()
        self.apply_column_visibility()

    def export_users_to_excel(self, _checked: bool = False) -> None:
        if not self.users:
            QMessageBox.information(
                self,
                "Экспорт Yandex 360",
                "Сначала загрузите пользователей выбранной организации.",
            )
            return
        org = self._current_org()
        org_name = org.domain if org and org.domain else (org.key if org else "organization")
        safe_org_name = re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", org_name).strip("._") or "organization"
        default_name = f"Yandex_360_{safe_org_name}_{datetime.now():%Y-%m-%d}.xlsx"
        documents_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default_path = str(Path(documents_dir or str(Path.home())) / default_name)
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Сохранить пользователей Yandex 360",
            default_path,
            "Книга Excel (*.xlsx)",
        )
        if not filename:
            return
        try:
            saved_path = export_yandex_users_xlsx(filename, self.users, org)
        except Exception as exc:
            self.log.add("ERROR", "Экспорт Excel", str(exc))
            self.context.audit.log(
                "yandex_export_xlsx",
                object_type="yandex360_user",
                object_name=filename,
                result="ERROR",
                message=str(exc),
            )
            QMessageBox.critical(self, "Экспорт Yandex 360", str(exc))
            return
        self.log.add("INFO", "Экспорт Excel", f"Сохранено пользователей: {len(self.users)}")
        self.context.audit.log(
            "yandex_export_xlsx",
            object_type="yandex360_user",
            object_name=str(saved_path),
            result="SUCCESS",
            message=f"Выгружено пользователей: {len(self.users)}",
        )
        QMessageBox.information(
            self,
            "Экспорт Yandex 360",
            f"Файл Excel сохранён:\n{saved_path}\n\nПользователей: {len(self.users)}",
        )

    def apply_column_visibility(self) -> None:
        if not hasattr(self, "table"):
            return
        visible = set(self._visible_columns())
        for column, title in enumerate(self.COLUMNS):
            self.table.setColumnHidden(column, title not in visible)

    def _visible_columns(self) -> list[str]:
        configured = [column for column in self.context.config.yandex_visible_columns if column in self.COLUMNS]
        return configured or list(self.COLUMNS)

    def set_selected_enabled(self, enabled: bool) -> None:
        if not self._ensure_authorized():
            return
        org = self._current_org()
        user = self._selected_user()
        if not org or not user:
            QMessageBox.information(self, "Почта Yandex", "Выберите пользователя в таблице.")
            return
        action = "разблокировать" if enabled else "заблокировать"
        if QMessageBox.question(self, "Почта Yandex", f"{action.capitalize()} пользователя?\n{user.email or user.nickname}") != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            updated = set_yandex_user_enabled(org, user.id, enabled)
        except Exception as exc:
            self.log.add("ERROR", "Yandex status", str(exc))
            self.context.audit.log("yandex_set_enabled", object_type="yandex360_user", object_name=user.email, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "Почта Yandex", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.log.add("INFO", "Yandex status", f"{updated.email or user.email}: {'активна' if enabled else 'заблокирована'}")
        self.context.audit.log("yandex_set_enabled", object_type="yandex360_user", object_name=updated.email or user.email, result="SUCCESS")
        self.load_users()

    def generate_create_password(self, _checked: bool = False) -> None:
        self.create_password.setText(generate_ad_password(10))

    def _ensure_authorized(self) -> bool:
        return self.admin_authorized or self.request_admin_auth()

    def _current_org(self) -> YandexOrg | None:
        key = self.org_combo.currentData()
        for org in self.orgs:
            if org.key == key:
                return org
        return self.orgs[0] if self.orgs else None

    def _selected_user(self) -> YandexUser | None:
        row = self.table.currentRow()
        if 0 <= row < len(self.users):
            return self.users[row]
        return None

    def _populate_users_table(self) -> None:
        self.table.setRowCount(0)
        for user in self.users:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                user.email,
                user.nickname,
                user.display_name,
                self._status(user),
                format_datetime(user.created_at),
                format_datetime(user.updated_at),
                format_datetime(user.enabled_updated_at, "не изменялся"),
                user.id,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                if column == 3:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

    def _status(self, user: YandexUser) -> str:
        if user.is_dismissed:
            return "уволен"
        return "активна" if user.is_enabled else "заблокирована"

    def _mail_message(self, email: str = "") -> str:
        login = self.create_login.text().strip()
        password = self.create_password.text().strip()
        last_name, first_name, middle_name = parse_full_name(self.create_full_name.text())
        full_name = " ".join(part for part in [last_name, first_name, middle_name] if part)
        org = self._current_org()
        address = email or (f"{login}@{org.domain}" if org and org.domain and login else login)
        if not address or not password or not full_name:
            return ""
        return "\n".join(
            [
                f"Тема: Доступ к корпоративной почте - {full_name}",
                "",
                f"Здравствуйте{', ' + first_name if first_name else ''}.",
                "",
                "Для Вас создан почтовый ящик Yandex 360.",
                "",
                "Почта Yandex 360",
                f"Адрес: {address}",
                f"Первичный пароль: {password}",
                "Вход: https://mail.360.yandex.ru/",
                "",
                "Первый вход",
                "При первом входе система может попросить заменить первичный пароль на личный.",
                "Новый пароль должен быть известен только сотруднику.",
                "",
                "Карточка сотрудника",
                f"ФИО: {full_name}",
                f"Должность: {self.create_position.text().strip() or 'не указана'}",
            ]
        )
