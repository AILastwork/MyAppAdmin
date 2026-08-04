from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.services.ad_directory import (
    build_login_candidates,
    generate_password as generate_ad_password,
    list_organizational_units,
    list_security_groups,
    parse_full_name,
    suggest_login,
)
from app.services.ad_service import AdCreateUserRequest, AdService
from app.services.user_provisioning import UserProvisioningRequest, UserProvisioningService
from app.services.v8i import list_template_profiles
from app.services.yandex360 import YandexCreateUserRequest, create_yandex_user, find_yandex_org, format_datetime, load_yandex_orgs
from app.ui.ad_admin_auth import AdAdminCredentials, request_ad_admin_credentials, request_privileged_operation_authorization
from app.ui.context import PageContext
from app.ui.widgets import Card, OperationLog, button, page_title


class LazyAdComboBox(QComboBox):
    def __init__(self, loader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._loaded_once = False
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = self.completer()
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        if self.lineEdit():
            self.lineEdit().textEdited.connect(self._show_matches)

    def showPopup(self) -> None:
        if not self._ensure_loaded():
            return
        super().showPopup()

    def mark_loaded(self) -> None:
        self._loaded_once = True

    def _ensure_loaded(self) -> bool:
        if self._loaded_once:
            return True
        self._loaded_once = True
        if self._loader() is False:
            self._loaded_once = False
            return False
        return True

    def _show_matches(self, text: str) -> None:
        if not self._ensure_loaded():
            return
        completer = self.completer()
        completer.setCompletionPrefix(text)
        completer.complete()


class CreateUserPage(QWidget):
    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self._auto_login = ""
        self.admin_authorized = False
        self.admin_credentials: AdAdminCredentials | None = None
        self._action_buttons: list[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(page_title("Создание пользователя Active Directory"))
        layout.addWidget(self._build_auth_card())

        vertical_splitter = QSplitter(Qt.Vertical)
        splitter = QSplitter(Qt.Horizontal)
        form_area = QScrollArea()
        form_area.setWidgetResizable(True)
        form_area.setFrameShape(QFrame.Shape.NoFrame)
        form_area.setWidget(self._build_form_card())
        splitter.addWidget(form_area)
        splitter.addWidget(self._build_preview_card())
        splitter.setSizes([950, 430])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        vertical_splitter.addWidget(splitter)

        self.log = OperationLog()
        self.log.setMinimumHeight(150)
        vertical_splitter.addWidget(self.log)
        vertical_splitter.setSizes([640, 240])
        vertical_splitter.setStretchFactor(0, 4)
        vertical_splitter.setStretchFactor(1, 1)
        vertical_splitter.setChildrenCollapsible(False)
        layout.addWidget(vertical_splitter, 1)
        self.refresh()

    def on_activate(self) -> None:
        return

    def _build_auth_card(self) -> QWidget:
        card = Card("Доступ к созданию пользователя")
        row = QHBoxLayout()
        self.auth_status = QLabel("Требуется проверка доменного администратора AD")
        auth_btn = button("Проверить AD-админа", primary=True)
        auth_btn.clicked.connect(self.request_admin_auth)
        row.addWidget(self.auth_status, 1)
        row.addWidget(auth_btn)
        card.layout.addLayout(row)
        return card

    def _build_form_card(self) -> QWidget:
        card = Card("Основные данные")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)

        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("Никишин Андрей Олегович")
        self.full_name.setToolTip("Введите ФИО одной строкой. Фамилия, имя и отчество заполняются автоматически.")
        self.full_name.textEdited.connect(self._autofill_identity_from_full_name)
        self.full_name.editingFinished.connect(self.auto_suggest_login)
        self.last_name = QLineEdit()
        self.last_name.setPlaceholderText("Иванов")
        self.first_name = QLineEdit()
        self.first_name.setPlaceholderText("Иван")
        self.middle_name = QLineEdit()
        self.middle_name.setPlaceholderText("Сергеевич")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Системный администратор")
        self.login = QLineEdit()
        self.login.setPlaceholderText("i.ivanov")
        self.login.setToolTip("Латиница, цифры, точка, подчеркивание или дефис. Используется как имя папки USERFOLDER\\login.")
        self.login.textChanged.connect(self._sync_upn)
        self.login.textEdited.connect(self._mark_login_as_manual)
        login_row = QWidget()
        login_layout = QHBoxLayout(login_row)
        login_layout.setContentsMargins(0, 0, 0, 0)
        login_layout.setSpacing(8)
        suggest_login_btn = button("Подобрать")
        suggest_login_btn.clicked.connect(self.suggest_login)
        login_layout.addWidget(self.login, 1)
        login_layout.addWidget(suggest_login_btn)
        self.password = QLineEdit()
        self.password.setPlaceholderText("10 символов: a/A/0/!@_")
        self.password.setToolTip("Пароль генерируется длиной 10 символов: строчные, заглавные, цифры и один из !@_.")
        password_row = QWidget()
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(8)
        password_btn = button("Сгенерировать")
        password_btn.clicked.connect(self.generate_password)
        password_layout.addWidget(self.password, 1)
        password_layout.addWidget(password_btn)
        self.upn = QLineEdit()
        self.upn.setPlaceholderText("i.ivanov@osnova.local")
        self.ou = LazyAdComboBox(self.load_ous_from_ad)
        self.ou.setPlaceholderText("Введите часть названия или DN OU")
        self.ou.setToolTip("Пример: OU=Users,DC=osnova,DC=local")
        ou_row = QWidget()
        ou_layout = QHBoxLayout(ou_row)
        ou_layout.setContentsMargins(0, 0, 0, 0)
        ou_layout.setSpacing(8)
        load_ou_btn = button("Загрузить")
        load_ou_btn.clicked.connect(self.load_ous_from_ad)
        ou_layout.addWidget(self.ou, 1)
        ou_layout.addWidget(load_ou_btn)
        self.change_password = QCheckBox("Сменить пароль при первом входе")
        self.change_password.setChecked(True)
        self.create_yandex_mail = QCheckBox("Создать почту Yandex 360")
        self.create_yandex_mail.setChecked(False)
        self.create_yandex_mail.toggled.connect(self._ensure_mail_password)
        self.mail_domain = QComboBox()
        self.mail_domain.setEditable(True)
        self.mail_domain.setToolTip("Домен Yandex 360, например mkd-osnova.ru. Список берется из token-файла, если он доступен.")
        self.mail_password = QLineEdit()
        self.mail_password.setPlaceholderText("Если пусто, используется пароль AD")
        self.mail_password.setToolTip("Первичный пароль ящика Yandex 360. Пустое поле означает пароль AD, как в веб-приложении.")
        mail_password_row = QWidget()
        mail_password_layout = QHBoxLayout(mail_password_row)
        mail_password_layout.setContentsMargins(0, 0, 0, 0)
        mail_password_layout.setSpacing(8)
        mail_password_btn = button("Сгенерировать")
        mail_password_btn.clicked.connect(self.generate_mail_password)
        mail_password_layout.addWidget(self.mail_password, 1)
        mail_password_layout.addWidget(mail_password_btn)
        self.create_files = QCheckBox("Создать папки scan и файлы 1C")
        self.create_files.setChecked(True)
        self.files_root = QLineEdit(self.context.config.userfolder_root)
        self.files_root.setPlaceholderText(r"\\osnova.local\fs\USERFOLDER")
        self.files_root.setToolTip("Корень личных пользовательских папок. Итог: <корень>\\login.")
        self.scan_root = QLineEdit(self.context.config.user_scan_root)
        self.scan_root.setPlaceholderText(r"\\osnova.local\fs\SCAN")
        self.scan_root.setToolTip("Корень папок scan. Итог: <корень>\\login\\scan.")
        self.onec_root = QLineEdit(self.context.config.user_1c_root)
        self.onec_root.setPlaceholderText(r"\\osnova.local\fs\IBASE")
        self.onec_root.setToolTip("Корень файлов 1C. Итог: <корень>\\login\\ibases.v8i и 1CEStart.cfg.")
        self.template_profile = QComboBox()
        self.template_profile.setToolTip("Шаблон ibases.v8i из template_dir. Можно выбрать один из нескольких профилей.")
        self.overwrite_v8i = QCheckBox("Перезаписать существующий ibases.v8i шаблоном")
        self.overwrite_v8i.setChecked(False)
        self.overwrite_v8i.setToolTip("Включайте только для тестовой папки или когда нужно заменить список баз у существующего пользователя.")

        form.addRow("ФИО", self.full_name)
        form.addRow("Фамилия", self.last_name)
        form.addRow("Имя", self.first_name)
        form.addRow("Отчество", self.middle_name)
        form.addRow("Должность", self.title)
        form.addRow("Login", login_row)
        form.addRow("Пароль", password_row)
        form.addRow("UPN / email", self.upn)
        form.addRow("OU", ou_row)
        form.addRow("", self.change_password)
        form.addRow("", self.create_yandex_mail)
        form.addRow("Yandex домен", self.mail_domain)
        form.addRow("Пароль Yandex", mail_password_row)
        form.addRow("", self.create_files)
        form.addRow("Папка пользователя", self.files_root)
        form.addRow("Папка scan", self.scan_root)
        form.addRow("Файлы 1C", self.onec_root)
        form.addRow("Шаблон ibases", self.template_profile)
        form.addRow("", self.overwrite_v8i)
        card.layout.addLayout(form)

        group_header = QHBoxLayout()
        group_header.addWidget(QLabel("Группы безопасности"))
        load_groups_btn = button("Загрузить")
        load_groups_btn.clicked.connect(self.load_groups_from_ad)
        group_header.addWidget(load_groups_btn)
        group_header.addStretch(1)
        card.layout.addLayout(group_header)
        group_security_note = QLabel(
            "Административные группы исключены. Приложение блокирует их по имени, SID, "
            "adminCount и вложенному членству."
        )
        group_security_note.setWordWrap(True)
        group_security_note.setStyleSheet("color: #9fc7c1;")
        card.layout.addWidget(group_security_note)
        group_pick_row = QHBoxLayout()
        self.group_combo = LazyAdComboBox(self.load_groups_from_ad)
        self.group_combo.setPlaceholderText("Введите часть названия группы")
        self.group_combo.activated.connect(self.add_security_group_from_combo)
        self.group_combo.completer().activated[str].connect(self.add_security_group_from_combo)
        if self.group_combo.lineEdit():
            self.group_combo.lineEdit().returnPressed.connect(self.add_security_group_from_combo)
        add_group_btn = button("Добавить")
        add_group_btn.clicked.connect(self.add_security_group_from_combo)
        group_pick_row.addWidget(self.group_combo, 1)
        group_pick_row.addWidget(add_group_btn)
        card.layout.addLayout(group_pick_row)

        self.selected_groups_frame = QFrame()
        selected_groups_layout = QVBoxLayout(self.selected_groups_frame)
        selected_groups_layout.setContentsMargins(0, 0, 0, 0)
        selected_groups_layout.setSpacing(6)
        selected_groups_layout.addWidget(QLabel("Выбранные группы (двойной щелчок удаляет группу)"))
        self.selected_groups = QListWidget()
        self.selected_groups.setMaximumHeight(86)
        self.selected_groups.itemDoubleClicked.connect(self.remove_security_group)
        selected_groups_layout.addWidget(self.selected_groups)
        selected_group_actions = QHBoxLayout()
        remove_group_btn = button("Удалить выбранную")
        remove_group_btn.clicked.connect(self.remove_selected_security_groups)
        clear_groups_btn = button("Очистить")
        clear_groups_btn.clicked.connect(self.clear_security_groups)
        selected_group_actions.addWidget(remove_group_btn)
        selected_group_actions.addWidget(clear_groups_btn)
        selected_group_actions.addStretch(1)
        selected_groups_layout.addLayout(selected_group_actions)
        card.layout.addWidget(self.selected_groups_frame)
        self._update_selected_groups_visibility()

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        create_user_btn = button("Создать пользователя", primary=True)
        create_user_btn.clicked.connect(self.create_user)
        copy_mail_btn = button("Скопировать письмо")
        copy_mail_btn.clicked.connect(self.copy_employee_message)
        clear_btn = button("Очистить форму")
        clear_btn.clicked.connect(self.clear_form)
        self.actions_layout = actions
        self._action_buttons = [create_user_btn, copy_mail_btn, clear_btn]
        self._relayout_action_buttons()
        card.layout.addLayout(self.actions_layout)
        return card

    def _build_preview_card(self) -> QWidget:
        card = Card("Предпросмотр операции")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.progress_frame = QFrame()
        self.progress_frame.setProperty("role", "mailProgress")
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(14, 12, 14, 12)
        progress_layout.setSpacing(8)
        progress_head = QHBoxLayout()
        self.progress_title = QLabel("Создание пользователя")
        self.progress_title.setObjectName("ProgressTitle")
        self.progress_status = QLabel("Ожидание запуска")
        self.progress_status.setObjectName("ProgressStatus")
        progress_head.addWidget(self.progress_title)
        progress_head.addStretch(1)
        progress_head.addWidget(self.progress_status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addLayout(progress_head)
        progress_layout.addWidget(self.progress_bar)
        self.progress_frame.setVisible(False)
        card.layout.addWidget(self.progress_frame)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("После запуска здесь появится результат создания и письмо сотруднику.")
        card.layout.addWidget(self.preview)
        return card

    def refresh(self) -> None:
        self.refresh_template_profiles()
        current_ou = self.ou.currentText() if hasattr(self, "ou") else ""
        self.ou.clear()
        if current_ou:
            self.ou.setCurrentText(current_ou)

        current_mail_domain = self.mail_domain.currentText() if hasattr(self, "mail_domain") else ""
        self.mail_domain.clear()
        domains = [org.domain for org in load_yandex_orgs(self.context.config.yandex_token_file) if org.domain]
        self.mail_domain.addItems(domains)
        if current_mail_domain:
            self.mail_domain.setCurrentText(current_mail_domain)
        elif domains:
            self.mail_domain.setCurrentText(domains[0])

        self._populate_group_options([])
        if hasattr(self, "files_root") and not self.files_root.text().strip():
            self.files_root.setText(self.context.config.userfolder_root)
        if hasattr(self, "scan_root") and not self.scan_root.text().strip():
            self.scan_root.setText(self.context.config.user_scan_root)
        if hasattr(self, "onec_root") and not self.onec_root.text().strip():
            self.onec_root.setText(self.context.config.user_1c_root)
        self._update_selected_groups_visibility()

    def refresh_template_profiles(self) -> None:
        if not hasattr(self, "template_profile"):
            return
        current = self.template_profile.currentText().strip() or self.context.config.default_1c_profile
        self.template_profile.clear()
        profiles = [profile.name for profile in list_template_profiles(self.context.config.template_dir)]
        if not profiles and self.context.config.default_1c_profile:
            profiles = [self.context.config.default_1c_profile]
        self.template_profile.addItems(profiles)
        if current:
            index = self.template_profile.findText(current, Qt.MatchExactly)
            if index >= 0:
                self.template_profile.setCurrentIndex(index)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_action_buttons()

    def _relayout_action_buttons(self) -> None:
        if not hasattr(self, "actions_layout") or not self._action_buttons:
            return
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        width = max(1, self.width())
        columns = 1 if width < 760 else 2 if width < 1120 else 3
        for index, action_button in enumerate(self._action_buttons):
            self.actions_layout.addWidget(action_button, index // columns, index % columns)
        self.actions_layout.setColumnStretch(columns, 1)

    def request_admin_auth(self, _checked: bool = False) -> bool:
        self.admin_credentials = request_ad_admin_credentials(self.context, self, "Создание пользователя")
        self.admin_authorized = self.admin_credentials is not None
        if self.admin_authorized:
            self.auth_status.setText(
                f"Подтверждена учетная запись {self.admin_credentials.username}. Данные действуют для одной операции."
            )
        else:
            self.auth_status.setText("Создание пользователей заблокировано до проверки доменной учетной записи.")
        return self.admin_authorized

    def _ensure_authorized(self) -> bool:
        return self.admin_authorized or self.request_admin_auth()

    def _clear_admin_authorization(self) -> None:
        self.admin_credentials = None
        self.admin_authorized = False
        self.auth_status.setText("Требуется проверка доменного администратора AD")

    def load_ous_from_ad(self, _checked: bool = False) -> bool:
        current_ou = self.ou.currentText().strip()
        try:
            values = list_organizational_units(self.context.config)
        except Exception as exc:
            self.log.add("ERROR", "OU из AD", str(exc))
            QMessageBox.warning(self, "OU из AD", str(exc))
            return False
        self.ou.clear()
        self.ou.addItems(values)
        self.ou.mark_loaded()
        if current_ou:
            self.ou.setCurrentText(current_ou)
        elif values:
            self.ou.setCurrentText(values[0])
        self.log.add("INFO", "OU из AD", f"Загружено OU: {len(values)}")
        return True

    def load_groups_from_ad(self, _checked: bool = False) -> bool:
        try:
            values = list_security_groups(self.context.config)
        except Exception as exc:
            self.log.add("ERROR", "Группы из AD", str(exc))
            QMessageBox.warning(self, "Группы из AD", str(exc))
            return False
        ad_service = AdService(self.context.config)
        allowed_values = [
            group for group in values
            if not ad_service.group_policy_error(group)
        ]
        self._populate_group_options(allowed_values)
        self.group_combo.mark_loaded()
        hidden_count = len(values) - len(allowed_values)
        self.log.add(
            "INFO",
            "Группы из AD",
            f"Загружено групп: {len(allowed_values)}; административных скрыто: {hidden_count}",
        )
        return True

    def add_security_group_from_combo(self, _selected: object = None) -> None:
        group = _selected.strip() if isinstance(_selected, str) else self.group_combo.currentText().strip()
        if not group:
            return
        policy_error = AdService(self.context.config).group_policy_error(group)
        if policy_error:
            self.group_combo.clearEditText()
            QMessageBox.warning(self, "Группа AD запрещена", policy_error)
            return
        for index in range(self.selected_groups.count()):
            item = self.selected_groups.item(index)
            if item.text().strip().lower() == group.lower():
                self.selected_groups.setCurrentItem(item)
                self.group_combo.clearEditText()
                return
        item = QListWidgetItem(group)
        self.selected_groups.addItem(item)
        self.selected_groups.setCurrentItem(item)
        self.group_combo.clearEditText()
        self._update_selected_groups_visibility()

    def remove_security_group(self, item: QListWidgetItem) -> None:
        row = self.selected_groups.row(item)
        if row >= 0:
            self.selected_groups.takeItem(row)
        self._update_selected_groups_visibility()

    def remove_selected_security_groups(self, _checked: bool = False) -> None:
        for item in self.selected_groups.selectedItems():
            self.selected_groups.takeItem(self.selected_groups.row(item))
        self._update_selected_groups_visibility()

    def clear_security_groups(self, _checked: bool = False) -> None:
        self.selected_groups.clear()
        self._update_selected_groups_visibility()

    def _update_selected_groups_visibility(self) -> None:
        if hasattr(self, "selected_groups_frame"):
            self.selected_groups_frame.setVisible(self.selected_groups.count() > 0)

    def build_plan(self) -> None:
        try:
            self._save_create_user_file_settings()
            if not self.password.text().strip():
                self.generate_password()
            self._auto_split_full_name()
            if not self.login.text().strip():
                self.suggest_login()
            request = self._request()
            plan = AdService(self.context.config).build_create_user_plan(request)
        except Exception as exc:
            self.log.add("ERROR", "План AD", str(exc))
            QMessageBox.warning(self, "Ошибка", str(exc))
            return

        lines = [plan.title, ""]
        lines.extend(f"{index}. {step}" for index, step in enumerate(plan.steps, start=1))
        if plan.warnings:
            lines.append("")
            lines.append("Предупреждения:")
            lines.extend(f"- {warning}" for warning in plan.warnings)
        lines.extend(self._workspace_preview_lines(request.login))
        message = self._employee_message()
        if message:
            lines.extend(["", "Письмо сотруднику:", "", message])
        self.preview.setPlainText("\n".join(lines))
        self.log.add("INFO", "План AD", "План операции сформирован")
        self.context.audit.log("ad_create_plan", object_type="ad_user", object_name=request.login, params={"warnings": plan.warnings})

    def create_user(self, _checked: bool = False) -> None:
        try:
            self._save_create_user_file_settings()
            if not self.password.text().strip():
                self.generate_password()
            self._auto_split_full_name()
            if not self.login.text().strip():
                self.suggest_login()
            request = self._request()
            plan = AdService(self.context.config).build_create_user_plan(request)
            if request.create_yandex_mail:
                if not request.mail_domain:
                    raise ValueError("Выберите домен Yandex 360.")
                find_yandex_org(load_yandex_orgs(self.context.config.yandex_token_file), request.mail_domain)
        except Exception as exc:
            self.log.add("ERROR", "Создание пользователя", str(exc))
            QMessageBox.warning(self, "Создание пользователя", str(exc))
            return

        warning_block = ""
        if plan.warnings:
            warning_block = "\n\nПредупреждения:\n" + "\n".join(f"- {warning}" for warning in plan.warnings)
        groups = ", ".join(request.groups) if request.groups else "без групп"
        optional_steps = [
            f"Почта Yandex 360: {'создать' if request.create_yandex_mail else 'не создавать'}",
            f"Файлы и папки: {'создать' if self.create_files.isChecked() else 'не создавать'}",
        ]
        question = (
            "Будет выполнено создание пользователя.\n\n"
            f"Login: {request.login}\n"
            f"UPN: {request.upn}\n"
            f"ФИО: {' '.join(part for part in [request.last_name, request.first_name, request.middle_name] if part)}\n"
            f"OU: {request.ou_dn}\n"
            f"Группы AD: {groups}\n"
            + "\n".join(optional_steps)
            + f"{warning_block}\n\n"
            "Продолжить?"
        )
        if QMessageBox.question(self, "Создать пользователя", question) != QMessageBox.Yes:
            return

        if not self._ensure_authorized() or not self.admin_credentials:
            self.log.add("INFO", "Создание пользователя", "Операция отменена: проверка доменной учетной записи не пройдена")
            return
        credentials = self.admin_credentials

        self._set_create_controls_enabled(False)
        self._set_create_progress(0, 1, "Подготовка операции...")
        try:
            template_path = self._selected_template_path()
            result = UserProvisioningService(self.context.config).provision(
                UserProvisioningRequest(
                    ad_request=request,
                    operator_username=credentials.username,
                    operator_password=credentials.password,
                    create_files=self.create_files.isChecked(),
                    userfolder_root=self.files_root.text().strip(),
                    scan_root=self.scan_root.text().strip(),
                    onec_root=self.onec_root.text().strip(),
                    template_path=template_path if template_path.exists() else None,
                    overwrite_v8i=self.overwrite_v8i.isChecked(),
                ),
                progress=self._set_create_progress,
            )
        except Exception as exc:
            self._set_create_progress(0, 1, "Ошибка", visible=False)
            self.log.add("ERROR", "Создание пользователя", str(exc))
            self.context.audit.log("create_user_flow", object_type="ad_user", object_name=request.login, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "Создание пользователя", str(exc))
            return
        finally:
            self._clear_admin_authorization()
            self._set_create_controls_enabled(True)

        ad_result = result.ad
        created_lines = [
            "Пользователь создан в AD.",
            f"Login: {ad_result.login}",
            f"UPN: {ad_result.upn}",
            f"ФИО: {ad_result.display_name}",
            f"DN: {ad_result.dn}",
            f"Группы AD: {', '.join(ad_result.groups) if ad_result.groups else 'без групп'}",
        ]
        self.log.add("INFO", "Создание AD", f"Создан пользователь: {ad_result.login}")
        self.context.audit.log("ad_create_user", object_type="ad_user", object_name=ad_result.login, result="SUCCESS", message=ad_result.dn)

        if result.mail:
            email = result.mail.email or self._mail_address(request.login, request.mail_domain)
            created_lines.extend(
                [
                    "",
                    "Почта Yandex 360 создана.",
                    f"Email: {email}",
                    f"Статус: {'активна' if result.mail.is_enabled else 'заблокирована'}",
                    f"Создана: {format_datetime(result.mail.created_at)}",
                ]
            )
            self.log.add("INFO", "Почта Yandex", f"Создан ящик: {email}")
            self.context.audit.log("yandex_create_user", object_type="yandex360_user", object_name=email, result="SUCCESS")

        if result.workspace:
            workspace = result.workspace
            created_lines.extend(
                [
                    "",
                    "Папки и файлы созданы или проверены.",
                    f"Папка пользователя: {workspace.user_dir}",
                    f"Папка scan: {workspace.scan_dir}",
                    f"ibases.v8i: {workspace.ibases_path}",
                    f"1CEStart.cfg: {workspace.start_cfg_path}",
                ]
            )
            self.log.add("INFO", "Файлы 1C", f"Создано/проверено: {workspace.user_dir}")
            self.context.audit.log(
                "create_user_workspace",
                object_type="user_files",
                object_name=request.login,
                result="SUCCESS",
                params={
                    "user_dir": str(workspace.user_dir),
                    "scan_dir": str(workspace.scan_dir),
                    "onec_dir": str(workspace.onec_dir),
                    "ibases_path": str(workspace.ibases_path),
                    "start_cfg_path": str(workspace.start_cfg_path),
                },
            )
        if result.acl_results and not any(item.returncode != 0 for item in result.acl_results):
            created_lines.append("Права на папки применены.")
            self.context.audit.log("apply_acl", object_type="user_files", object_name=request.login, result="SUCCESS")

        if result.issues:
            created_lines.extend(["", "Операция завершена с предупреждениями:"])
            for issue in result.issues:
                created_lines.append(f"- {issue.stage}: {issue.message}")
                self.log.add("ERROR", issue.stage, issue.message)
                self.context.audit.log(
                    "create_user_stage",
                    object_type="ad_user",
                    object_name=request.login,
                    result="ERROR",
                    message=f"{issue.stage}: {issue.message}",
                )

        message = self._employee_message(include_mail=result.mail is not None)
        lines = created_lines
        if message:
            lines.extend(["", "Письмо сотруднику:", "", message])
            QApplication.clipboard().setText(message)
        self.preview.setPlainText("\n".join(lines))
        flow_result = "WARNING" if result.issues else "SUCCESS"
        self.context.audit.log("create_user_flow", object_type="ad_user", object_name=request.login, result=flow_result)
        if result.issues:
            QMessageBox.warning(self, "Создание пользователя", f"AD-пользователь создан, но есть предупреждения:\n{request.login}")
        else:
            QMessageBox.information(self, "Создание пользователя", f"Пользователь создан:\n{request.login}")

    def create_ad_user(self) -> None:
        self.create_user()

    def create_yandex_mailbox(self) -> None:
        if not request_privileged_operation_authorization(self.context, "Создание почты Yandex 360", self):
            self.log.add("INFO", "Почта Yandex", "Операция отменена: проверка доменной учетной записи не пройдена")
            return
        try:
            self._auto_split_full_name()
            if not self.password.text().strip():
                self.generate_password()
            if not self.mail_password.text().strip():
                self.generate_mail_password()
            if not self.login.text().strip():
                self.suggest_login()
            request = self._request()
            if not request.mail_domain:
                raise ValueError("Выберите домен Yandex 360.")
            org = find_yandex_org(load_yandex_orgs(self.context.config.yandex_token_file), request.mail_domain)
        except Exception as exc:
            self.log.add("ERROR", "Почта Yandex", str(exc))
            QMessageBox.warning(self, "Почта Yandex", str(exc))
            return

        email = self._mail_address(request.login, request.mail_domain)
        question = (
            "Будет создан сотрудник Yandex 360 через API.\n\n"
            f"Организация: {org.name or org.key}\n"
            f"Email: {email}\n"
            f"ФИО: {' '.join(part for part in [request.last_name, request.first_name, request.middle_name] if part)}\n\n"
            "Продолжить?"
        )
        if QMessageBox.question(self, "Создать почту Yandex", question) != QMessageBox.Yes:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = create_yandex_user(
                org,
                YandexCreateUserRequest(
                    nickname=request.login,
                    password=request.mail_password,
                    first_name=request.first_name,
                    last_name=request.last_name,
                    middle_name=request.middle_name,
                    position=request.title,
                    department_id=org.department_id,
                    password_change_required=True,
                ),
            )
        except Exception as exc:
            self.log.add("ERROR", "Почта Yandex", str(exc))
            self.context.audit.log("yandex_create_user", object_type="yandex360_user", object_name=email, result="ERROR", message=str(exc))
            QMessageBox.critical(self, "Почта Yandex", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.create_yandex_mail.setChecked(True)
        self.preview.setPlainText(
            "\n".join(
                [
                    "Почта Yandex 360 создана.",
                    "",
                    f"Email: {result.email or email}",
                    f"Login: {result.nickname}",
                    f"Статус: {'активна' if result.is_enabled else 'заблокирована'}",
                    f"Создана: {format_datetime(result.created_at)}",
                    "",
                    self._employee_message(include_ad=False, include_mail=True),
                ]
            )
        )
        self.log.add("INFO", "Почта Yandex", f"Создан ящик: {result.email or email}")
        self.context.audit.log("yandex_create_user", object_type="yandex360_user", object_name=result.email or email, result="SUCCESS")
        QMessageBox.information(self, "Почта Yandex", f"Ящик создан:\n{result.email or email}")

    def _set_create_progress(self, current: int, total: int, status: str, *, visible: bool = True) -> None:
        if not hasattr(self, "progress_frame"):
            return
        self.progress_frame.setVisible(visible)
        self.progress_status.setText(status)
        maximum = max(1, total)
        value = max(0, min(maximum, current))
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)
        QApplication.processEvents()

    def _set_create_controls_enabled(self, enabled: bool) -> None:
        for action_button in self._action_buttons:
            action_button.setEnabled(enabled)

    def clear_form(self) -> None:
        for field in [self.full_name, self.last_name, self.first_name, self.middle_name, self.title, self.login, self.password, self.upn, self.mail_password]:
            field.clear()
        self.create_yandex_mail.setChecked(False)
        self.clear_security_groups()
        self.preview.clear()
        self.log.add("INFO", "Форма", "Форма очищена")

    def _auto_split_full_name(self, _text: str = "") -> None:
        last_name, first_name, middle_name = parse_full_name(self.full_name.text())
        self.last_name.setText(last_name)
        self.first_name.setText(first_name)
        self.middle_name.setText(middle_name)

    def _autofill_identity_from_full_name(self, _text: str = "") -> None:
        self._auto_split_full_name()
        candidates = build_login_candidates(
            self.last_name.text().strip(),
            self.first_name.text().strip(),
            self.middle_name.text().strip(),
        )
        generated_login = candidates[0] if candidates else ""
        current_login = self.login.text().strip()
        if generated_login and (not current_login or current_login == self._auto_login):
            self.login.setText(generated_login)
            self._auto_login = generated_login
            self._set_upn_for_login(generated_login)

    def _mark_login_as_manual(self, _text: str = "") -> None:
        self._auto_login = ""

    def split_full_name(self, _checked: bool = False) -> None:
        self._auto_split_full_name()
        last_name = self.last_name.text().strip()
        first_name = self.first_name.text().strip()
        middle_name = self.middle_name.text().strip()
        if not self.login.text().strip():
            candidates = build_login_candidates(last_name, first_name, middle_name)
            if candidates:
                self.login.setText(candidates[0])
                self._set_upn_for_login(candidates[0])

    def auto_suggest_login(self) -> None:
        if self.login.text().strip():
            return
        self.suggest_login()

    def suggest_login(self, _checked: bool = False) -> None:
        self.split_full_name()
        suggestion = suggest_login(
            self.context.config,
            self.last_name.text().strip(),
            self.first_name.text().strip(),
            self.middle_name.text().strip(),
        )
        if suggestion.login:
            self.login.setText(suggestion.login)
            self._set_upn_for_login(suggestion.login)
        if suggestion.warning:
            self.log.add("ERROR" if not suggestion.login else "INFO", "Подбор login", suggestion.warning)
        else:
            self.log.add("INFO", "Подбор login", "Login проверен в AD" if suggestion.verified_in_ad else "Login сформирован без проверки AD")

    def generate_password(self, _checked: bool = False) -> None:
        self.password.setText(generate_ad_password(10))

    def generate_mail_password(self, _checked: bool = False) -> None:
        self.mail_password.setText(generate_ad_password(10))

    def copy_employee_message(self, _checked: bool = False) -> None:
        if not self.password.text().strip():
            self.generate_password()
        message = self._employee_message()
        if not message:
            QMessageBox.warning(self, "Письмо сотруднику", "Заполните login и ФИО.")
            return
        QApplication.clipboard().setText(message)
        self.preview.setPlainText(message)
        self.log.add("INFO", "Письмо сотруднику", "Текст письма скопирован в буфер обмена")

    def _request(self) -> AdCreateUserRequest:
        return AdCreateUserRequest(
            last_name=self.last_name.text().strip(),
            first_name=self.first_name.text().strip(),
            middle_name=self.middle_name.text().strip(),
            title=self.title.text().strip(),
            login=self.login.text().strip(),
            password=self.password.text().strip(),
            upn=self.upn.text().strip(),
            ou_dn=self.ou.currentText().strip(),
            groups=self._selected_groups(),
            change_password_at_logon=self.change_password.isChecked(),
            create_yandex_mail=self.create_yandex_mail.isChecked(),
            mail_domain=self.mail_domain.currentText().strip(),
            mail_password=self.mail_password.text().strip() or self.password.text().strip(),
        )

    def _ensure_mail_password(self, checked: bool) -> None:
        if checked and not self.mail_password.text().strip():
            self.mail_password.setPlaceholderText("Будет использован пароль AD")

    def _selected_groups(self) -> list[str]:
        return [
            self.selected_groups.item(index).text()
            for index in range(self.selected_groups.count())
        ]

    def _populate_group_options(self, groups: list[str]) -> None:
        current_group = self.group_combo.currentText().strip() if hasattr(self, "group_combo") else ""
        values = _unique_texts(groups)
        if hasattr(self, "group_combo"):
            self.group_combo.clear()
            self.group_combo.addItems(values)
            self.group_combo.setCurrentIndex(-1)
            if current_group:
                self.group_combo.setEditText(current_group)

    def _sync_upn(self, _text: str = "") -> None:
        login = self.login.text().strip()
        if login and "@" not in self.upn.text():
            self._set_upn_for_login(login)

    def _set_upn_for_login(self, login: str) -> None:
        suffix = self.context.config.base_dn.replace("DC=", "").replace(",", ".").lower()
        self.upn.setText(f"{login}@{suffix}")

    def _workspace_preview_lines(self, login: str) -> list[str]:
        if not self.create_files.isChecked() or not login.strip():
            return []
        root = self.files_root.text().strip() or self.context.config.userfolder_root
        scan_root = self.scan_root.text().strip() or self.context.config.user_scan_root
        onec_root = self.onec_root.text().strip() or self.context.config.user_1c_root
        user_dir = Path(root) / login.strip()
        scan_dir = Path(scan_root) / login.strip() / "scan"
        onec_dir = Path(onec_root) / login.strip()
        ibases_path = onec_dir / "ibases.v8i"
        start_cfg_path = onec_dir / "1CEStart.cfg"
        template_path = self._selected_template_path()
        return [
            "",
            "Пути создаваемых файлов:",
            f"- Корень личной папки: {root}",
            f"- Папка пользователя: {user_dir}",
            f"- Корень scan: {scan_root}",
            f"- Scan: {scan_dir}",
            f"- Корень файлов 1C: {onec_root}",
            f"- ibases.v8i: {ibases_path}",
            f"- 1CEStart.cfg: {start_cfg_path}",
            f"- Шаблон 1C: {template_path if template_path.exists() else 'не найден, будет создан пустой ibases.v8i'}",
            f"- Права: {login.strip()} и Domain Admins — Full; {self.context.config.scan_account} — Modify только на scan",
        ]

    def _selected_template_path(self) -> Path:
        profile = self.template_profile.currentText().strip() if hasattr(self, "template_profile") else ""
        return self.context.config.template_path(profile or None)

    def _save_create_user_file_settings(self) -> None:
        root = self.files_root.text().strip() if hasattr(self, "files_root") else ""
        if root:
            self.context.config.userfolder_root = root
        scan_root = self.scan_root.text().strip() if hasattr(self, "scan_root") else ""
        if scan_root:
            self.context.config.user_scan_root = scan_root
        onec_root = self.onec_root.text().strip() if hasattr(self, "onec_root") else ""
        if onec_root:
            self.context.config.user_1c_root = onec_root
        profile = self.template_profile.currentText().strip() if hasattr(self, "template_profile") else ""
        if profile:
            self.context.config.default_1c_profile = profile
        if self.context.on_config_changed:
            self.context.on_config_changed()

    def _employee_message(self, *, include_ad: bool = True, include_mail: bool | None = None) -> str:
        login = self.login.text().strip()
        last_name = self.last_name.text().strip()
        first_name = self.first_name.text().strip()
        middle_name = self.middle_name.text().strip()
        full_name = " ".join(part for part in [last_name, first_name, middle_name] if part)
        if not login or not full_name:
            return ""

        mail_enabled = self.create_yandex_mail.isChecked() if include_mail is None else include_mail
        return build_employee_message(
            full_name=full_name,
            login=login,
            ad_password=self.password.text().strip(),
            mail_address=self._mail_address(login, self.mail_domain.currentText().strip()),
            mail_password=self.mail_password.text().strip() or self.password.text().strip(),
            include_ad=include_ad,
            include_mail=mail_enabled,
        )

    def _mail_address(self, login: str, domain: str) -> str:
        mail_domain = domain.strip() or self.upn.text().strip().split("@", 1)[-1]
        return f"{login}@{mail_domain}" if mail_domain else login


def build_employee_message(
    *,
    full_name: str,
    login: str,
    ad_password: str,
    mail_address: str,
    mail_password: str,
    include_ad: bool = True,
    include_mail: bool = True,
) -> str:
    lines = ["Добрый день."]
    if include_mail:
        lines.extend(
            [
                "Для Вас создан ящик электронной почты",
                "",
                "Доступ в почту: https://mail.360.yandex.ru/",
                f"- {mail_address}",
                f"- {mail_password}",
                "",
            ]
        )
    if include_ad:
        lines.extend(
            [
                "Учетная запись для доступа к компьютеру",
                f"- {login}",
                f"- {ad_password}",
                "",
            ]
        )
    lines.extend(
        [
            "Пароли необходимо сменить при первом входе.",
            "",
            "Новый сотрудник:",
            f"- {full_name}",
        ]
    )
    return "\n".join(lines)


def _unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
