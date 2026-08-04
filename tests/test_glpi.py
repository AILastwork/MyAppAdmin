from __future__ import annotations

import pytest

from app.services.glpi import (
    GlpiAuthenticationError,
    GlpiWebClient,
    build_search_terms,
    parse_computer_list,
    parse_login_form,
    parse_pager,
    search_computers,
)
from app.ui.pages.glpi import format_computer_details


LOGIN_HTML = """
<html><head><title>GLPI - Аутентификация</title></head>
<body>
  <form action="/front/login.php" method="post">
    <input type="hidden" name="redirect" value="/front/computer.php"/>
    <input type="text" name="field_login_dynamic" id="login_name"/>
    <input type="password" name="field_password_dynamic" id="login_password"/>
    <input type="checkbox" name="field_remember_dynamic" id="login_remember" checked="checked"/>
    <input type="hidden" name="auth" value="local"/>
    <input type="hidden" name="_glpi_csrf_token" value="csrf-token"/>
  </form>
</body></html>
"""


COMPUTERS_HTML = """
<html><body>
<table class="tab_cadre_pager"><tr><td>С 1 по 2 из 2</td></tr></table>
<table class="tab_cadrehov">
  <tr>
    <th></th>
    <th><a href="/front/computer.php?sort=1">Наименование</a></th>
    <th>Производитель</th>
    <th>Серийный номер</th>
    <th>Тип</th>
    <th>Модель</th>
    <th>Последнее изменение</th>
    <th>Компоненты - Процессор</th>
    <th>Сетевая структура - MAC-адрес</th>
    <th>Сетевая структура - IP</th>
    <th>Компоненты - Тип HDD</th>
    <th>Компоненты - Память</th>
    <th>Компоненты - Тип памяти</th>
    <th>Антивирусы - Наименование</th>
    <th>Операционная система - Наименование</th>
    <th>Операционная система - Версия</th>
    <th>Плагины - FusInv - Last boot</th>
    <th>Контактное лицо</th>
  </tr>
  <tr>
    <td><input type="checkbox" name="item[Computer][42]" /></td>
    <td><a href="/front/computer.form.php?id=42">WRK-102</a></td>
    <td>ASUSTeK COMPUTER INC.</td>
    <td>181139683810816</td>
    <td>Desktop</td>
    <td>PRIME H310M-R R2.0</td>
    <td>2026-06-18 08:53</td>
    <td>Intel Core i5-8600</td>
    <td>40:b0:76:42:2a:9a</td>
    <td>fe80::11e9 10.14.32.251</td>
    <td>KINGSTON SA400S37120G</td>
    <td>8 Гб</td>
    <td>DDR4 - DIMM</td>
    <td>Windows Defender</td>
    <td>Windows</td>
    <td>2009</td>
    <td>2026-06-18 08:53</td>
    <td>d.gluhov@OSNOVA</td>
  </tr>
  <tr>
    <td><input type="checkbox" name="item[Computer][5]" /></td>
    <td><a href="/front/computer.form.php?id=5">WRK-112</a></td>
    <td>ASUSTeK COMPUTER INC.</td>
    <td>190855907103768</td>
    <td>Desktop</td>
    <td>H110M-R</td>
    <td>2026-04-07 09:41</td>
    <td>Intel Core i5-7600</td>
    <td>04:d9:f5:c9:19:03</td>
    <td>10.14.32.176</td>
    <td>Apacer AS340 240GB</td>
    <td>16 Гб</td>
    <td>DDR4 - DIMM</td>
    <td>Windows Defender</td>
    <td>Windows</td>
    <td>2009</td>
    <td>2026-04-07 11:43</td>
    <td>admin@WRK-112</td>
  </tr>
</table>
</body></html>
"""


class FakeResponse:
    def __init__(self, text: str, url: str = "http://glpi.local/") -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


def test_parse_login_form_supports_dynamic_glpi_field_names():
    form = parse_login_form(LOGIN_HTML, "http://glpi.local/index.php")

    assert form.action == "http://glpi.local/front/login.php"
    assert form.login_field == "field_login_dynamic"
    assert form.password_field == "field_password_dynamic"
    assert form.remember_field == "field_remember_dynamic"
    assert form.fields["_glpi_csrf_token"] == "csrf-token"


def test_parse_computer_list_and_pager():
    computers = parse_computer_list(COMPUTERS_HTML, "http://glpi.local")

    assert parse_pager(COMPUTERS_HTML) == (1, 2, 2)
    assert len(computers) == 2
    assert computers[0].glpi_id == "42"
    assert computers[0].name == "WRK-102"
    assert computers[0].contact == "d.gluhov@OSNOVA"
    assert computers[0].ipv4_addresses == ["10.14.32.251"]
    assert computers[0].display_ip == "10.14.32.251"
    assert computers[0].mac_addresses == ["40:b0:76:42:2a:9a"]
    assert computers[0].url == "http://glpi.local/front/computer.form.php?id=42"


def test_search_computers_matches_full_name_login_and_computer_name():
    computers = parse_computer_list(COMPUTERS_HTML, "http://glpi.local")

    by_full_name = search_computers(computers, "Глухов Дмитрий")
    by_reversed_name = search_computers(computers, "Дмитрий Глухов")
    by_login = search_computers(computers, "d.gluhov")
    by_computer = search_computers(computers, "WRK-112")
    by_partial_last_name = search_computers(computers, "Глух")
    by_partial_two_words = search_computers(computers, "Дмит Глу")
    by_first_name = search_computers(computers, "Дмитрий")

    assert by_full_name[0].computer.name == "WRK-102"
    assert by_reversed_name[0].computer.name == "WRK-102"
    assert by_login[0].computer.name == "WRK-102"
    assert by_computer[0].computer.glpi_id == "5"
    assert by_partial_last_name[0].computer.name == "WRK-102"
    assert by_partial_two_words[0].computer.name == "WRK-102"
    assert by_first_name[0].computer.name == "WRK-102"
    assert "d.gluhov" in build_search_terms("Глухов Дмитрий")


def test_glpi_details_show_human_readable_ipv4_without_ipv6():
    computer = parse_computer_list(COMPUTERS_HTML, "http://glpi.local")[0]
    details = format_computer_details(search_computers([computer], "Глух")[0])

    assert "Сеть" in details
    assert "IP: 10.14.32.251" in details
    assert "fe80::11e9" not in details
    assert "Железо" in details
    assert "ПО и инвентаризация" in details


def test_glpi_client_login_posts_dynamic_fields_and_loads_computers():
    calls = []

    class FakeSession:
        headers = {}

        def get(self, url, **_kwargs):
            calls.append(("GET", url, None))
            if "/front/computer.php" in url:
                return FakeResponse(COMPUTERS_HTML, url)
            return FakeResponse(LOGIN_HTML, url)

        def post(self, url, data, **_kwargs):
            calls.append(("POST", url, data))
            return FakeResponse("<html><title>GLPI - Центральная</title></html>", url)

    client = GlpiWebClient("http://glpi.local", session=FakeSession())
    client.login("a.nikitin", "secret")
    computers = client.load_computers()

    post_payload = next(data for method, _url, data in calls if method == "POST")
    assert post_payload["field_login_dynamic"] == "a.nikitin"
    assert post_payload["field_password_dynamic"] == "secret"
    assert post_payload["_glpi_csrf_token"] == "csrf-token"
    assert [computer.name for computer in computers] == ["WRK-102", "WRK-112"]


def test_glpi_client_rejects_login_page_after_authentication():
    class FakeSession:
        headers = {}

        def get(self, url, **_kwargs):
            return FakeResponse(LOGIN_HTML, url)

        def post(self, url, data, **_kwargs):
            return FakeResponse(LOGIN_HTML, url)

    client = GlpiWebClient("http://glpi.local", session=FakeSession())

    with pytest.raises(GlpiAuthenticationError):
        client.login("a.nikitin", "bad")
