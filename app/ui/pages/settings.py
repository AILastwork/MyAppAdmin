from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.security import is_current_user_domain_admin
from app.ui.context import PageContext
from app.ui.widgets import button, page_title


LIST_FIELDS = {"ad_search_visible_columns", "yandex_visible_columns"}
BOOL_FIELDS = {"service_mode_enabled"}
PASSWORD_FIELDS = {"ad_read_password", "kyocera_admin_password", "kyocera_smb_password"}
SECTION_MANAGED_FIELDS = {
    "userfolder_root",
    "user_scan_root",
    "user_1c_root",
    "default_1c_profile",
    "ad_search_visible_columns",
    "yandex_visible_columns",
}
INTERNAL_FIELDS = {"audit_db", "scan_account", "service_mode_enabled"}
HIDDEN_FIELDS = SECTION_MANAGED_FIELDS | INTERNAL_FIELDS
THEME_OPTIONS = [("dark", "Тёмная"), ("matrix", "Matrix")]

FIELD_HINTS = {
    "domain": "OSNOVA",
    "base_dn": "DC=osnova,DC=local",
    "app_theme": "dark",
    "ad_ldap_server": "osnova.local или dc01.osnova.local",
    "ad_ldaps_port": "636",
    "ad_read_user": r"OSNOVA\read_user или read_user@osnova.local",
    "ad_read_password": "Пароль учетной записи для чтения AD",
    "ad_search_limit": "50",
    "ad_search_visible_columns": "Login\nФИО\nПочта\nОтдел\nДолжность\nСтатус",
    "userfolder_root": r"\\osnova.local\fs\USERFOLDER",
    "user_scan_root": r"\\osnova.local\fs\SCAN",
    "user_1c_root": r"\\osnova.local\fs\IBASE",
    "template_dir": r"\\osnova.local\fs\IT\MyAppAdmin",
    "yandex_token_file": r"\\osnova.local\fs\IT\MyAppAdmin\API_yandex360.txt",
    "printer_config_file": r"пример: \\osnova.local\fs\IT\MyAppAdmin\printers.json",
    "glpi_base_url": "http://glpi.osnova.local",
    "audit_db": r"%APPDATA%\MyAppAdmin\audit.db",
    "default_1c_profile": "default.v8i",
    "scan_account": "scan_user.osnova.local",
    "service_mode_enabled": "false",
    "kyocera_script_path": "kyocera_add.py",
    "kyocera_admin_login": "Admin",
    "kyocera_admin_password": "Пароль администратора Kyocera",
    "kyocera_smb_host": "osnova.local",
    "kyocera_smb_port": "445",
    "kyocera_smb_username": r"osnova.local\scan_user",
    "kyocera_smb_password": "Пароль scan-учетки для SMB",
    "kyocera_smb_base_path": r"fs\USERFOLDER",
}

LIST_FIELD_HINTS = {
    "ad_search_visible_columns": "Login\nФИО\nПочта\nТелефон\nОтдел\nДолжность\nСтатус\nOU",
}


class SettingsPage(QWidget):
    def __init__(self, context: PageContext) -> None:
        super().__init__()
        self.context = context
        self.inputs: dict[str, QLineEdit | QPlainTextEdit | QComboBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)
        outer.addWidget(page_title("Настройки"))

        self.can_edit = is_current_user_domain_admin()
        if not self.can_edit:
            message = QLabel(
                "Изменение настроек доступно только участникам группы Domain Admins. "
                "Текущий пользователь может работать с разрешенными разделами программы, "
                "но не может просматривать или изменять конфигурацию."
            )
            message.setWordWrap(True)
            outer.addWidget(message)
            outer.addStretch(1)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.form = QFormLayout(inner)
        self.form.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        save_btn = button("Сохранить настройки", primary=True)
        save_btn.clicked.connect(self.save)
        outer.addWidget(save_btn)
        self.refresh()

    def refresh(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.inputs.clear()

        for item in fields(AppConfig):
            if item.name in HIDDEN_FIELDS:
                continue
            value = getattr(self.context.config, item.name)
            if item.name == "app_theme":
                widget = QComboBox()
                for key, label in THEME_OPTIONS:
                    widget.addItem(label, key)
                index = widget.findData(str(value or "dark"))
                widget.setCurrentIndex(index if index >= 0 else 0)
                self.inputs[item.name] = widget
                self.form.addRow(item.name, widget)
                continue
            if item.name in BOOL_FIELDS:
                widget = QComboBox()
                widget.addItem("false", False)
                widget.addItem("true", True)
                widget.setCurrentIndex(1 if bool(value) else 0)
                self.inputs[item.name] = widget
                self.form.addRow(item.name, widget)
                continue
            if item.name in LIST_FIELDS:
                widget = QPlainTextEdit()
                widget.setPlainText("\n".join(value))
                widget.setPlaceholderText(LIST_FIELD_HINTS.get(item.name, "Значения построчно"))
                widget.setToolTip("Заполняйте по одному значению на строку. Также поддерживается разделитель ; при загрузке конфига.")
                widget.setMinimumHeight(90)
                self.inputs[item.name] = widget
                self.form.addRow(item.name, widget)
                continue
            else:
                widget = QLineEdit(str(value))
                if item.name in PASSWORD_FIELDS:
                    widget.setEchoMode(QLineEdit.Password)
                hint = FIELD_HINTS.get(item.name)
                if hint:
                    widget.setPlaceholderText(hint)
                    widget.setToolTip(f"Пример: {hint}")
            self.inputs[item.name] = widget
            self.form.addRow(item.name, widget)

    def save(self) -> None:
        if not is_current_user_domain_admin():
            QMessageBox.warning(
                self,
                "Настройки",
                "Изменение настроек доступно только участникам группы Domain Admins.",
            )
            return
        for name, widget in self.inputs.items():
            if name in LIST_FIELDS:
                value = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
            elif name in BOOL_FIELDS:
                value = bool(widget.currentData()) if isinstance(widget, QComboBox) else widget.text().strip().lower() in {"1", "true", "yes", "да"}
            elif name == "app_theme":
                value = str(widget.currentData()) if isinstance(widget, QComboBox) else widget.text().strip()
            else:
                value = widget.text().strip()
            setattr(self.context.config, name, value)
        if self.context.on_config_changed:
            self.context.on_config_changed()
        QMessageBox.information(self, "Настройки", f"Настройки сохранены:\n{self.context.config_path}")
