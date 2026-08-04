from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar

from app.config import AppConfig
from app.ui.pages.create_user import CreateUserPage, LazyAdComboBox, build_employee_message


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_lazy_ad_combo_filters_matches_inside_text():
    _application()
    loads: list[bool] = []
    combo: LazyAdComboBox

    def load() -> bool:
        loads.append(True)
        combo.clear()
        combo.addItems(
            [
                "OU=Accounting,OU=Users,DC=osnova,DC=local",
                "OU=IT,OU=Users,DC=osnova,DC=local",
                "VPN Users",
            ]
        )
        combo.mark_loaded()
        return True

    combo = LazyAdComboBox(load)
    combo.lineEdit().textEdited.emit("count")
    model = combo.completer().completionModel()

    assert combo.completer().filterMode() == Qt.MatchContains
    assert loads == [True]
    assert [model.index(row, 0).data() for row in range(model.rowCount())] == [
        "OU=Accounting,OU=Users,DC=osnova,DC=local"
    ]


def test_create_progress_accepts_service_callback_arguments():
    _application()
    page = SimpleNamespace(
        progress_frame=QFrame(),
        progress_status=QLabel(),
        progress_bar=QProgressBar(),
    )

    CreateUserPage._set_create_progress(page, 2, 4, "Создание папок...")

    assert not page.progress_frame.isHidden()
    assert page.progress_status.text() == "Создание папок..."
    assert page.progress_bar.maximum() == 4
    assert page.progress_bar.value() == 2


def test_create_user_full_name_autofills_login_and_upn():
    _application()
    page = SimpleNamespace(
        context=SimpleNamespace(config=AppConfig(base_dn="DC=osnova,DC=local")),
        _auto_login="",
        full_name=QLineEdit("Морозова Екатерина Андреевна"),
        last_name=QLineEdit(),
        first_name=QLineEdit(),
        middle_name=QLineEdit(),
        login=QLineEdit(),
        upn=QLineEdit(),
    )
    page._auto_split_full_name = lambda: CreateUserPage._auto_split_full_name(page)
    page._set_upn_for_login = lambda login: CreateUserPage._set_upn_for_login(page, login)

    CreateUserPage._autofill_identity_from_full_name(page)

    assert page.login.text() == "e.morozova"
    assert page.upn.text() == "e.morozova@osnova.local"


def test_security_groups_are_added_from_combo_without_duplicates():
    _application()
    combo = QComboBox()
    combo.setEditable(True)
    page = SimpleNamespace(
        context=SimpleNamespace(config=AppConfig()),
        group_combo=combo,
        selected_groups=QListWidget(),
        selected_groups_frame=QFrame(),
    )
    page._update_selected_groups_visibility = lambda: CreateUserPage._update_selected_groups_visibility(page)

    combo.setEditText("VPN Users")
    CreateUserPage.add_security_group_from_combo(page)
    combo.setEditText("vpn users")
    CreateUserPage.add_security_group_from_combo(page)
    combo.setEditText("1C Users")
    CreateUserPage.add_security_group_from_combo(page)

    assert CreateUserPage._selected_groups(page) == ["VPN Users", "1C Users"]
    assert not page.selected_groups_frame.isHidden()

    CreateUserPage.clear_security_groups(page)

    assert CreateUserPage._selected_groups(page) == []
    assert page.selected_groups_frame.isHidden()


def test_administrative_group_cannot_be_added_manually(monkeypatch):
    _application()
    combo = QComboBox()
    combo.setEditable(True)
    page = SimpleNamespace(
        context=SimpleNamespace(config=AppConfig()),
        group_combo=combo,
        selected_groups=QListWidget(),
        selected_groups_frame=QFrame(),
    )
    page._update_selected_groups_visibility = lambda: CreateUserPage._update_selected_groups_visibility(page)
    warnings = []
    monkeypatch.setattr(
        "app.ui.pages.create_user.QMessageBox.warning",
        lambda *_args: warnings.append(True),
    )

    combo.setEditText("DnsAdmins")
    CreateUserPage.add_security_group_from_combo(page)

    assert CreateUserPage._selected_groups(page) == []
    assert warnings == [True]


def test_employee_message_uses_standard_template():
    message = build_employee_message(
        full_name="Морозова Екатерина Андреевна",
        login="e.morozova",
        ad_password="dRjT0k@JrO",
        mail_address="e.morozova@mkd-osnova.ru",
        mail_password="7ePPp!TewC",
    )

    assert message == (
        "Добрый день.\n"
        "Для Вас создан ящик электронной почты\n"
        "\n"
        "Доступ в почту: https://mail.360.yandex.ru/\n"
        "- e.morozova@mkd-osnova.ru\n"
        "- 7ePPp!TewC\n"
        "\n"
        "Учетная запись для доступа к компьютеру\n"
        "- e.morozova\n"
        "- dRjT0k@JrO\n"
        "\n"
        "Пароли необходимо сменить при первом входе.\n"
        "\n"
        "Новый сотрудник:\n"
        "- Морозова Екатерина Андреевна"
    )
