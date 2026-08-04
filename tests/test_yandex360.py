from __future__ import annotations

from app.services.yandex360 import YandexCreateUserRequest, YandexOrg, create_yandex_user, format_datetime, load_yandex_orgs


def test_load_yandex_orgs_from_ini_format(tmp_path):
    path = tmp_path / "yandex.ini"
    path.write_text(
        """
[mkd]
name = MKD
domain = mkd-osnova.ru
org_id = 4175672
department_id = 7
token = y0__fake
""".strip(),
        encoding="utf-8",
    )

    orgs = load_yandex_orgs(path)

    assert len(orgs) == 1
    assert orgs[0].key == "mkd"
    assert orgs[0].name == "MKD"
    assert orgs[0].domain == "mkd-osnova.ru"
    assert orgs[0].org_id == "4175672"
    assert orgs[0].department_id == "7"
    assert orgs[0].has_token is True
    assert orgs[0].token == "y0__fake"


def test_load_yandex_orgs_from_legacy_org_id_format(tmp_path):
    path = tmp_path / "API_yandex360.txt"
    path.write_text(
        """
ORG_ID = 4175672   mkd-osnova.ru
y0__fake_mkd

ORG_ID = 8439839  entuziast-uk.ru
y0__fake_ent
""".strip(),
        encoding="utf-8",
    )

    orgs = load_yandex_orgs(path)

    assert [org.key for org in orgs] == ["mkd-osnova.ru", "entuziast-uk.ru"]
    assert [org.domain for org in orgs] == ["mkd-osnova.ru", "entuziast-uk.ru"]
    assert [org.org_id for org in orgs] == ["4175672", "8439839"]
    assert [org.department_id for org in orgs] == ["1", "1"]
    assert all(org.has_token for org in orgs)
    assert [org.token for org in orgs] == ["y0__fake_mkd", "y0__fake_ent"]


def test_create_yandex_user_posts_expected_payload(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "id": "42",
                "nickname": "i.ivanov",
                "email": "i.ivanov@example.ru",
                "name": {"first": "Иван", "last": "Иванов", "middle": "Иванович"},
                "isEnabled": True,
                "createdAt": "2026-06-08T10:00:00Z",
            }

    def fake_request(method, url, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["headers"] = kwargs["headers"]
        calls["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("app.services.yandex360.requests.request", fake_request)

    org = YandexOrg("example", "Example", "example.ru", "4175672", "1", True, token="secret")
    user = create_yandex_user(
        org,
        YandexCreateUserRequest(
            nickname="i.ivanov",
            password="Passw0rd!_",
            first_name="Иван",
            last_name="Иванов",
            middle_name="Иванович",
            position="Инженер",
        ),
    )

    assert calls["method"] == "POST"
    assert calls["url"].endswith("/directory/v1/org/4175672/users")
    assert calls["headers"]["Authorization"] == "OAuth secret"
    assert calls["json"]["nickname"] == "i.ivanov"
    assert calls["json"]["password"] == "Passw0rd!_"
    assert calls["json"]["passwordChangeRequired"] is True
    assert calls["json"]["name"] == {"first": "Иван", "last": "Иванов", "middle": "Иванович"}
    assert user.email == "i.ivanov@example.ru"


def test_yandex_datetime_helpers_handle_empty_values():
    assert format_datetime("") == "нет данных"
    assert format_datetime("", "не изменялся") == "не изменялся"


def test_yandex_datetime_helpers_format_iso_values():
    assert format_datetime("2026-06-08T10:00:00Z").startswith("08.06.2026 ")
