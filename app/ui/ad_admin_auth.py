from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QWidget

from app.services.ad_directory import verify_ad_admin_credentials
from app.ui.context import PageContext


@dataclass(slots=True)
class AdAdminCredentials:
    username: str
    password: str = field(repr=False)
    admin_dn: str


class AdAdminAuthDialog(QDialog):
    def __init__(self, context: PageContext, operation: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.operation = operation
        self.admin_dn = ""
        self.credentials: AdAdminCredentials | None = None
        self.setWindowTitle("Проверка доменной учетной записи")
        self.resize(460, 190)

        layout = QFormLayout(self)
        operation_label = QLabel(operation)
        operation_label.setWordWrap(True)
        layout.addRow("Операция", operation_label)
        self.username = QLineEdit()
        self.username.setPlaceholderText(r"OSNOVA\admin или admin@osnova.local")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Пароль доменной учетной записи")
        layout.addRow("Учетная запись", self.username)
        layout.addRow("Пароль", self.password)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._verify)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _verify(self) -> None:
        try:
            username = self.username.text().strip()
            password = self.password.text()
            self.admin_dn = verify_ad_admin_credentials(
                self.context.config,
                username,
                password,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Проверка AD", str(exc))
            return
        self.context.audit.log(
            "ad_admin_auth",
            object_type="ad_user",
            object_name=self.username.text().strip(),
            result="SUCCESS",
            message=f"AD authorization passed: {self.operation}",
        )
        self.credentials = AdAdminCredentials(username, password, self.admin_dn)
        self.password.clear()
        self.accept()


def request_ad_admin_credentials(
    context: PageContext,
    parent: QWidget | None = None,
    operation: str = "Опасная операция",
) -> AdAdminCredentials | None:
    dialog = AdAdminAuthDialog(context, operation, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.credentials


def request_ad_admin_authorization(context: PageContext, parent: QWidget | None = None, operation: str = "Опасная операция") -> bool:
    return request_ad_admin_credentials(context, parent, operation) is not None


def request_privileged_operation_authorization(context: PageContext, operation: str, parent: QWidget | None = None) -> bool:
    return request_ad_admin_authorization(context, parent, operation)
