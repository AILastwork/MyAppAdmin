from __future__ import annotations

from types import SimpleNamespace

from app.security import current_windows_groups, is_current_user_domain_admin


def test_windows_groups_decodes_utf8_whoami_output(monkeypatch):
    output = (
        '"OSNOVA\\Администраторы домена","Group",'
        '"S-1-5-21-1-2-3-512","Group used for deny only"\r\n'
    ).encode("utf-8")
    monkeypatch.setattr(
        "app.security.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=output),
    )

    groups = current_windows_groups()

    assert r"OSNOVA\Администраторы домена" in groups
    assert "S-1-5-21-1-2-3-512" in groups


def test_domain_admin_is_detected_by_group_sid():
    assert is_current_user_domain_admin(["S-1-5-21-1-2-3-512"])
    assert not is_current_user_domain_admin(["S-1-5-21-1-2-3-1141"])


def test_domain_admin_is_detected_by_localized_group_name():
    assert is_current_user_domain_admin([r"OSNOVA\Администраторы домена"])
    assert is_current_user_domain_admin([r"OSNOVA\Domain Admins"])
