from __future__ import annotations

from types import SimpleNamespace

from app.services.acl import (
    apply_workspace_acl,
    build_scan_acl_commands,
    build_workspace_acl_commands,
    normalize_acl_account,
    resolve_domain_admins_principal,
)


def test_build_workspace_acl_commands(monkeypatch):
    monkeypatch.setattr(
        "app.services.acl.current_windows_groups",
        lambda: ["S-1-5-21-1-2-3-512"],
    )
    commands = build_workspace_acl_commands(
        user_dir=r"\\server\share\i.ivanov",
        scan_dir=r"\\server\share\i.ivanov\scan",
        login="i.ivanov",
        domain="OSNOVA",
        scan_account="scan_user.osnova.local",
    )

    flat = [" ".join(command) for command in commands]
    assert any("OSNOVA\\i.ivanov" in command for command in flat)
    assert any("*S-1-5-21-1-2-3-512" in command for command in flat)
    assert any("OSNOVA\\scan_user" in command for command in flat)
    scan_commands = [command for command in flat if r"\\server\share\i.ivanov\scan" in command]
    assert any("OSNOVA\\i.ivanov:(OI)(CI)F" in command for command in scan_commands)
    assert any("*S-1-5-21-1-2-3-512:(OI)(CI)F" in command for command in scan_commands)
    assert any("OSNOVA\\scan_user:(OI)(CI)M" in command for command in scan_commands)
    assert commands[0][2] == "/grant:r"
    assert commands[1][2] == "/inheritance:r"


def test_build_workspace_acl_commands_handles_separate_1c_root(monkeypatch):
    monkeypatch.setattr(
        "app.services.acl.current_windows_groups",
        lambda: ["S-1-5-21-1-2-3-512"],
    )
    commands = build_workspace_acl_commands(
        user_dir=r"\\server\users\i.ivanov",
        scan_dir=r"\\server\scan\i.ivanov\scan",
        onec_dir=r"\\server\onec\i.ivanov",
        login="i.ivanov",
        domain="OSNOVA",
        scan_account="scan_user.osnova.local",
    )

    flat = [" ".join(command) for command in commands]
    assert any(r"\\server\onec\i.ivanov" in command and "OSNOVA\\i.ivanov:(OI)(CI)F" in command for command in flat)
    assert any(r"\\server\scan\i.ivanov\scan" in command and "OSNOVA\\scan_user:(OI)(CI)M" in command for command in flat)
    assert not any(r"\\server\users\i.ivanov" in command and "OSNOVA\\scan_user" in command for command in flat)
    assert not any(r"\\server\onec\i.ivanov" in command and "OSNOVA\\scan_user" in command for command in flat)


def test_build_scan_acl_commands_only_targets_scan_folder(monkeypatch):
    monkeypatch.setattr(
        "app.services.acl.current_windows_groups",
        lambda: ["S-1-5-21-1-2-3-512"],
    )

    commands = build_scan_acl_commands(
        scan_dir=r"\\server\users\i.ivanov\scan",
        login="i.ivanov",
        domain="OSNOVA",
        scan_account="scan_user.osnova.local",
    )

    assert len(commands) == 2
    assert all(command[1] == r"\\server\users\i.ivanov\scan" for command in commands)
    flat = " ".join(commands[0])
    assert r"OSNOVA\i.ivanov:(OI)(CI)F" in flat
    assert "*S-1-5-21-1-2-3-512:(OI)(CI)F" in flat
    assert r"OSNOVA\scan_user:(OI)(CI)M" in flat


def test_resolve_domain_admins_uses_domain_sid_from_current_user(monkeypatch):
    monkeypatch.setattr("app.services.acl.current_windows_groups", lambda: [])
    monkeypatch.setattr("app.services.acl._current_windows_user_sid", lambda: "S-1-5-21-10-20-30-1001")
    monkeypatch.setenv("USERDOMAIN", "OSNOVA")

    principal = resolve_domain_admins_principal("OSNOVA")

    assert principal == "*S-1-5-21-10-20-30-512"


def test_normalize_acl_account_converts_dotted_domain_login():
    assert normalize_acl_account("scan_user.osnova.local", "OSNOVA") == r"OSNOVA\scan_user"
    assert normalize_acl_account("scan_user@osnova.local", "OSNOVA") == "scan_user@osnova.local"


def test_apply_workspace_acl_decodes_oem_output_and_keeps_inheritance_on_grant_failure(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=1,
            stdout="Отказано в доступе.".encode("cp866"),
            stderr=b"",
        )

    monkeypatch.setattr("app.services.acl.subprocess.run", fake_run)
    commands = [
        ["icacls", r"\\server\share\user", "/grant:r", "OSNOVA\\user:(OI)(CI)F"],
        ["icacls", r"\\server\share\user", "/inheritance:r"],
    ]

    results = apply_workspace_acl(commands)

    assert calls == [commands[0]]
    assert results[0].stdout == "Отказано в доступе."
    assert results[1].returncode == 1
    assert "пропущено" in results[1].stderr
