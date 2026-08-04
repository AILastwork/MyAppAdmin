from __future__ import annotations

from contextlib import contextmanager
from app.config import AppConfig
from app.services.ad_service import AdCreateUserRequest, AdService


def test_create_user_uses_confirmed_operator_connection(monkeypatch):
    calls: dict[str, object] = {}
    connection = object()

    @contextmanager
    def fake_authorized_connection(config, username, password):
        calls["credentials"] = (username, password)
        yield connection, "CN=Administrator,OU=Admins,DC=example,DC=local"

    def fake_add_user(conn, config, **kwargs):
        calls["connection"] = conn
        calls["user"] = kwargs

    monkeypatch.setattr("app.services.ad_service.authorized_admin_connection", fake_authorized_connection)
    monkeypatch.setattr("app.services.ad_service.add_user_object", fake_add_user)

    config = AppConfig(base_dn="DC=example,DC=local")
    request = AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="Иванович",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=Users,DC=example,DC=local",
    )

    result = AdService(config).create_user(
        request,
        operator_username=r"EXAMPLE\admin",
        operator_password="AdminPass1!",
    )

    assert calls["credentials"] == (r"EXAMPLE\admin", "AdminPass1!")
    assert calls["connection"] is connection
    assert calls["user"]["login"] == "i.ivanov"
    assert result.login == "i.ivanov"


def test_create_user_requires_operator_credentials():
    config = AppConfig()
    request = AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=Users,DC=example,DC=local",
    )

    try:
        AdService(config).create_user(
            request,
            operator_username="",
            operator_password="",
        )
    except PermissionError as exc:
        assert "администратора AD" in str(exc)
    else:
        raise AssertionError("Ожидалась обязательная повторная авторизация администратора")


def test_create_plan_allows_any_ou_and_non_denied_group():
    request = AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=AnyDepartment,DC=example,DC=local",
        groups=["Custom Application Users"],
    )

    plan = AdService(AppConfig()).build_create_user_plan(request)

    assert plan.warnings == []
    assert any("Custom Application Users" in step for step in plan.steps)


def test_create_user_blocks_denied_group_before_connection():
    request = AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=Users,DC=example,DC=local",
        groups=["Domain Admins"],
    )

    try:
        AdService(AppConfig()).create_user(
            request,
            operator_username="admin",
            operator_password="secret",
        )
    except ValueError as exc:
        assert "административную группу" in str(exc)
    else:
        raise AssertionError("Ожидалась блокировка группы из denylist")


def test_admin_group_block_is_immutable():
    service = AdService(AppConfig())

    assert "административную группу" in service.group_policy_error("Администраторы домена")
    assert "административную группу" in service.group_policy_error("DnsAdmins")
    assert "административную группу" in service.group_policy_error("Администраторы Hyper-V")
    assert "административную группу" in service.group_policy_error("Custom Application Admins")
    assert service.group_policy_error("VPN Users") == ""


def test_create_plan_blocks_real_admin_group_example():
    request = AdCreateUserRequest(
        last_name="Тест1",
        first_name="Тест",
        middle_name="Тестович",
        login="t.test1",
        password="UserPass1!",
        upn="t.test1@osnova.local",
        ou_dn="OU=АРМ,OU=Отдел ИТ,DC=osnova,DC=local",
        groups=["Администраторы", "Администраторы Hyper-V", "Администраторы домена"],
    )

    try:
        AdService(AppConfig()).build_create_user_plan(request)
    except ValueError as exc:
        message = str(exc)
        assert "Администраторы" in message
        assert "Администраторы Hyper-V" in message
        assert "Администраторы домена" in message
    else:
        raise AssertionError("Административные группы должны блокироваться до создания пользователя")


def test_create_user_blocks_group_nested_in_protected_admin_group(monkeypatch):
    class Attribute:
        def __init__(self, value="", values=None):
            self.value = value
            self.values = list(values or [])

    class Entry:
        def __init__(self, dn, **attributes):
            self.entry_dn = dn
            self.attributes = {
                name: Attribute(
                    value=value if not isinstance(value, list) else "",
                    values=value if isinstance(value, list) else [],
                )
                for name, value in attributes.items()
            }

        def __getitem__(self, name):
            return self.attributes[name]

    child_dn = "CN=Helpdesk Tier 2,OU=Groups,DC=example,DC=local"
    parent_dn = "CN=Protected Delegation,OU=Groups,DC=example,DC=local"
    entries = {
        child_dn: Entry(
            child_dn,
            cn="Helpdesk Tier 2",
            sAMAccountName="Helpdesk Tier 2",
            objectSid="S-1-5-21-1-2-3-2100",
            adminCount="",
            memberOf=[parent_dn],
        ),
        parent_dn: Entry(
            parent_dn,
            cn="Protected Delegation",
            sAMAccountName="Protected Delegation",
            objectSid="S-1-5-21-1-2-3-2101",
            adminCount="1",
            memberOf=[],
        ),
    }

    class FakeConnection:
        def __init__(self):
            self.entries = []

        def search(self, search_base, *_args, **_kwargs):
            self.entries = [entries[search_base]] if search_base in entries else []
            return bool(self.entries)

    connection = FakeConnection()

    @contextmanager
    def fake_authorized_connection(*_args):
        yield connection, "CN=Administrator,OU=Admins,DC=example,DC=local"

    monkeypatch.setattr("app.services.ad_service.authorized_admin_connection", fake_authorized_connection)
    monkeypatch.setattr("app.services.ad_service.resolve_group_dn", lambda *_args: child_dn)
    monkeypatch.setattr(
        "app.services.ad_service.add_user_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("AD user must not be created")),
    )

    request = AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=Users,DC=example,DC=local",
        groups=["Helpdesk Tier 2"],
    )

    try:
        AdService(AppConfig()).create_user(
            request,
            operator_username="admin",
            operator_password="secret",
        )
    except ValueError as exc:
        assert "Защищенная группа в цепочке" in str(exc)
        assert "Protected Delegation" in str(exc)
    else:
        raise AssertionError("Ожидалась блокировка вложенной административной группы")
