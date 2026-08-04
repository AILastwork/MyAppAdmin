from __future__ import annotations

from types import SimpleNamespace

import kyocera_add
import requests


def test_discover_printer_base_url_follows_https_redirect(monkeypatch):
    monkeypatch.setattr(kyocera_add, "PRINTER_URL", "http://10.14.32.47")

    class FakeSession:
        headers = {"User-Agent": "test-agent"}

        def get(self, url, **_kwargs):
            assert url == "http://10.14.32.47/"
            return SimpleNamespace(
                status_code=200,
                url="https://10.14.32.47:443/",
            )

    result = kyocera_add.discover_printer_base_url(FakeSession())

    assert result == "https://10.14.32.47:443"
    assert kyocera_add.make_url("/startwlm/login.cgi") == (
        "https://10.14.32.47:443/startwlm/login.cgi"
    )


def test_kyocera_session_accepts_device_self_signed_certificate():
    assert kyocera_add.create_session().verify is False


def test_normalize_printer_url_accepts_plain_ip_and_preserves_https():
    assert kyocera_add.normalize_printer_url("10.14.32.47") == "http://10.14.32.47"
    assert kyocera_add.normalize_printer_url("https://10.14.32.47/") == "https://10.14.32.47"


def test_preflight_switches_to_https_when_only_port_443_is_available(monkeypatch):
    monkeypatch.setattr(kyocera_add, "PRINTER_URL", "http://10.14.32.47")
    checked_ports = []

    def fake_tcp_port_open(_host, port, timeout):
        checked_ports.append((port, timeout))
        return port == 443

    monkeypatch.setattr(kyocera_add, "tcp_port_open", fake_tcp_port_open)

    kyocera_add.preflight_printer_availability()

    assert kyocera_add.PRINTER_URL == "https://10.14.32.47"
    assert [port for port, _timeout in checked_ports] == [80, 443]
    assert kyocera_add.printer_port_from_url(kyocera_add.PRINTER_URL) == 443


def test_discover_retries_with_legacy_tls_after_ssl_error(monkeypatch):
    monkeypatch.setattr(kyocera_add, "PRINTER_URL", "https://10.14.32.47")
    calls = []

    class FakeSession:
        headers = {"User-Agent": "test-agent"}
        verify = True

        def get(self, _url, **_kwargs):
            calls.append("get")
            if len(calls) == 1:
                raise requests.exceptions.SSLError("certificate rejected")
            return SimpleNamespace(status_code=200, url="https://10.14.32.47/")

    session = FakeSession()
    monkeypatch.setattr(
        kyocera_add,
        "enable_legacy_tls_compatibility",
        lambda value: calls.append("legacy"),
    )

    assert kyocera_add.discover_printer_base_url(session) == "https://10.14.32.47"
    assert calls == ["get", "legacy", "get"]


def test_discover_rejects_unified_ews_interface(monkeypatch):
    monkeypatch.setattr(kyocera_add, "PRINTER_URL", "http://10.14.32.46")

    class FakeSession:
        headers = {"User-Agent": "test-agent"}

        def get(self, _url, **_kwargs):
            return SimpleNamespace(
                status_code=200,
                url="http://10.14.32.46/",
                text='<script src="/framework/Unified.js"></script><div id="pgm-overall-container"></div>',
            )

    try:
        kyocera_add.discover_printer_base_url(FakeSession())
    except RuntimeError as exc:
        assert "Unified/EWS" in str(exc)
    else:
        raise AssertionError("Unified/EWS должен определяться как отдельный неподдержанный интерфейс")


def test_contact_form_profile_preserves_firmware_fields_and_action():
    html = """
    <form name="adrscontact" action="../basic/custom-set.cgi" method="post">
      <input type="hidden" name="func" value="addAbpPersonal">
      <input type="hidden" name="hidden" value="firmware-token">
      <input type="hidden" name="arg41" value="0">
      <input type="radio" name="arg23_EncBox" value="1">
      <input type="radio" name="arg23_EncBox" value="0" checked>
      <input type="text" name="arg07_Name" value="">
      <input type="submit" name="submit001" value="Передать">
    </form>
    """

    profile = kyocera_add.extract_contact_form_profile(
        html,
        "https://printer/basic/AddrBook_Addr_NewCntct_Prpty.htm",
    )

    assert profile.action_url == "https://printer/basic/custom-set.cgi"
    assert ("arg41", "0") in profile.default_fields
    assert ("arg23_EncBox", "0") in profile.default_fields
    assert all(name != "submit001" for name, _value in profile.default_fields)


def test_contact_form_profile_ignores_knockout_placeholders_and_unchecked_radios():
    html = """
    <form name="adrscontact" action="/basic/set.cgi" method="post">
      <input type="hidden" name="func" value="addAbpPersonal">
      <input type="hidden" name="arg41" value="0">
      <input type="text" name="arg10_SMBPathName" value="smbPath" data-bind="value: smbPath">
      <input type="password" name="FCodePassword" value="faxPassword" data-bind="value: faxPassword">
      <input type="radio" name="arg23_EncBox" value="1" data-bind="checked: faxEncryptionBox">
      <input type="radio" name="arg23_EncBox" value="0" data-bind="checked: faxEncryptionBox">
      <input type="submit" name="submit001" value="mes()[243]">
    </form>
    """

    profile = kyocera_add.extract_contact_form_profile(
        html,
        "http://printer/basic/AddrBook_Addr_NewCntct_Prpty.htm",
    )
    fields = dict(profile.default_fields)

    assert fields == {"func": "addAbpPersonal", "arg41": "0"}


def test_contact_payload_overrides_data_but_keeps_firmware_defaults():
    contact = kyocera_add.KyoceraContact(
        number="017",
        name="Иванов И.",
        email="i.ivanov@example.ru",
        smb_host="server",
        smb_port="445",
        smb_path=r"fs\USERFOLDER\i.ivanov\scan",
        smb_username=r"DOMAIN\scan_user",
        smb_password="secret",
    )
    profile = kyocera_add.ContactFormProfile(
        "https://printer/basic/custom-set.cgi",
        [("func", "old"), ("arg41", "0"), ("hidden", "old-token")],
    )

    payload = dict(
        kyocera_add.build_add_contact_payload(
            contact,
            "current-token",
            profile,
        )
    )

    assert payload["func"] == "addAbpPersonal"
    assert payload["hidden"] == "current-token"
    assert payload["arg41"] == "0"
    assert payload["arg06_sID"] == "017"
    assert payload["arg09_SMBAddress"] == "server"
    assert payload["FTPPassword"] == ""


def test_add_contact_uses_single_post_and_verifies_after_lost_response(monkeypatch):
    contact = kyocera_add.KyoceraContact(
        number="017",
        name="Иванов И.",
        email="i.ivanov@example.ru",
        smb_host="server",
        smb_port="445",
        smb_path=r"fs\USERFOLDER\i.ivanov\scan",
        smb_username=r"DOMAIN\scan_user",
        smb_password="secret",
    )

    class FakeSession:
        headers = {"User-Agent": "test-agent"}

        def __init__(self):
            self.posts = 0

        def post(self, *_args, **_kwargs):
            self.posts += 1
            raise requests.exceptions.ReadTimeout("slow commit")

    session = FakeSession()
    verified = []
    monkeypatch.setattr(kyocera_add, "CONTACT_NUMBER", "017")
    monkeypatch.setattr(
        kyocera_add,
        "verify_contact_after_indeterminate_post",
        lambda _session, value, _error: verified.append(value.number) or True,
    )

    kyocera_add.add_contact(
        session,
        contact,
        "hiddenvalue",
        "https://printer/basic/AddrBook_Addr_NewCntct_Prpty.htm",
        kyocera_add.ContactFormProfile("https://printer/basic/set.cgi", []),
    )

    assert session.posts == 1
    assert verified == ["017"]


def test_post_add_contact_uses_close_header_and_long_commit_timeout():
    contact = kyocera_add.KyoceraContact(
        number="017",
        name="Иванов И.",
        email="i.ivanov@example.ru",
        smb_host="server",
        smb_port="445",
        smb_path=r"fs\USERFOLDER\i.ivanov\scan",
        smb_username=r"DOMAIN\scan_user",
        smb_password="secret",
    )
    seen = {}

    class FakeSession:
        headers = {"User-Agent": "test-agent"}

        def post(self, url, **kwargs):
            seen["url"] = url
            seen.update(kwargs)
            return SimpleNamespace(status_code=200, text="OK")

    kyocera_add.post_add_contact_once(
        FakeSession(),
        contact,
        "hiddenvalue",
        "https://printer/basic/AddrBook_Addr_NewCntct_Prpty.htm",
        kyocera_add.ContactFormProfile("https://printer/basic/set.cgi", []),
    )

    assert seen["url"] == "https://printer/basic/set.cgi"
    assert seen["timeout"] == kyocera_add.ADD_CONTACT_TIMEOUT_SECONDS
    assert seen["headers"]["Connection"] == "close"


def test_verify_contact_is_best_effort_after_successful_post(monkeypatch):
    contact = kyocera_add.KyoceraContact(
        number="017",
        name="Иванов И.",
        email="i.ivanov@example.ru",
        smb_host="server",
        smb_port="445",
        smb_path=r"fs\USERFOLDER\i.ivanov\scan",
        smb_username=r"DOMAIN\scan_user",
        smb_password="secret",
    )
    monkeypatch.setattr(kyocera_add, "contact_exists", lambda *_args, **_kwargs: False)

    assert kyocera_add.verify_contact(object(), contact) is False


def test_main_skips_addressbook_text_search_after_successful_post(monkeypatch):
    for name in [
        "PRINTER_URL",
        "KYOCERA_ADMIN_LOGIN",
        "KYOCERA_ADMIN_PASSWORD",
        "SMB_HOST",
        "SMB_PORT",
        "SMB_USERNAME",
        "SMB_PASSWORD",
        "SMB_BASE_PATH",
        "SMB_SCAN_SUBFOLDER",
        "CONTACT_FULL_NAME",
        "CONTACT_LOGIN",
        "CONTACT_EMAIL",
        "CONTACT_NUMBER",
    ]:
        monkeypatch.setattr(kyocera_add, name, getattr(kyocera_add, name))

    monkeypatch.setattr(
        kyocera_add,
        "parse_args",
        lambda: SimpleNamespace(
            printer="http://printer",
            admin_login="admin",
            admin_password="password",
            full_name="Иванов Иван",
            login="i.ivanov",
            email="i.ivanov@example.ru",
            number="",
            smb_host="server",
            smb_port="445",
            smb_username=r"DOMAIN\scan_user",
            smb_password="secret",
            smb_base_path=r"fs\USERFOLDER",
            smb_scan_subfolder="scan",
            check_only=False,
        ),
    )

    session = object()
    messages = []
    added = []
    monkeypatch.setattr(kyocera_add, "log", messages.append)
    monkeypatch.setattr(kyocera_add, "create_session", lambda: session)
    monkeypatch.setattr(kyocera_add, "preflight_printer_availability", lambda: None)
    monkeypatch.setattr(kyocera_add, "discover_printer_base_url", lambda _session: "http://printer")
    monkeypatch.setattr(kyocera_add, "wait_printer_ready", lambda _session, stage="startup": None)
    monkeypatch.setattr(kyocera_add, "login", lambda _session: None)
    monkeypatch.setattr(
        kyocera_add,
        "get_new_contact_model",
        lambda _session: ("017", "hiddenvalue", "http://printer/basic/new.htm"),
    )
    monkeypatch.setattr(
        kyocera_add,
        "load_contact_form_profile",
        lambda _session, _url: kyocera_add.ContactFormProfile("http://printer/basic/set.cgi", []),
    )
    monkeypatch.setattr(
        kyocera_add,
        "add_contact",
        lambda _session, contact, *_args: added.append((contact.number, contact.email)),
    )

    def fail_verify(*_args):
        raise AssertionError("verify_contact must not run after accepted POST")

    monkeypatch.setattr(kyocera_add, "verify_contact", fail_verify)

    assert kyocera_add.main() == 0
    assert added == [("017", "i.ivanov@example.ru")]
    assert any("Проверку списка после успешного POST не запускаю" in message for message in messages)
