from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.services.acl import AclCommandResult
from app.services.ad_service import AdCreateUserRequest, AdCreateUserResult
from app.services.user_files import UserWorkspaceResult
from app.services.user_provisioning import UserProvisioningRequest, UserProvisioningService
from app.services.yandex360 import YandexOrg, YandexUser


def _ad_request(mail_password: str = "") -> AdCreateUserRequest:
    return AdCreateUserRequest(
        last_name="Иванов",
        first_name="Иван",
        middle_name="Иванович",
        login="i.ivanov",
        password="UserPass1!",
        upn="i.ivanov@example.local",
        ou_dn="OU=Users,DC=example,DC=local",
        title="Инженер",
        create_yandex_mail=True,
        mail_domain="example.ru",
        mail_password=mail_password,
    )


def _workspace() -> UserWorkspaceResult:
    user_dir = Path("users") / "i.ivanov"
    scan_dir = Path("scan") / "i.ivanov" / "scan"
    onec_dir = Path("onec") / "i.ivanov"
    return UserWorkspaceResult(
        login="i.ivanov",
        user_dir=user_dir,
        scan_dir=scan_dir,
        onec_dir=onec_dir,
        ibases_path=onec_dir / "ibases.v8i",
        start_cfg_path=onec_dir / "1CEStart.cfg",
        created_user_dir=True,
        created_scan_dir=True,
        created_onec_dir=True,
        wrote_ibases=True,
        wrote_start_cfg=True,
    )


def test_provisioning_matches_web_password_fallback_and_runs_all_steps(monkeypatch):
    calls: dict[str, object] = {}
    org = YandexOrg("example", "Example", "example.ru", "42", "1", True, token="token")

    def fake_create_ad(self, request, *, operator_username, operator_password):
        calls["operator"] = (operator_username, operator_password)
        return AdCreateUserResult(request.login, request.upn, "Иванов Иван Иванович", "CN=User,OU=Users")

    def fake_create_mail(selected_org, request):
        calls["mail_password"] = request.password
        calls["mail_change_required"] = request.password_change_required
        return YandexUser("7", request.nickname, "i.ivanov@example.ru", "Иванов Иван Иванович", True)

    monkeypatch.setattr("app.services.user_provisioning.AdService.create_user", fake_create_ad)
    monkeypatch.setattr("app.services.user_provisioning.load_yandex_orgs", lambda _path: [org])
    monkeypatch.setattr("app.services.user_provisioning.find_yandex_org", lambda _orgs, _domain: org)
    monkeypatch.setattr("app.services.user_provisioning.create_yandex_user", fake_create_mail)
    monkeypatch.setattr("app.services.user_provisioning.create_user_workspace", lambda **_kwargs: _workspace())
    monkeypatch.setattr("app.services.user_provisioning.build_workspace_acl_commands", lambda **_kwargs: [["icacls", "users"]])
    monkeypatch.setattr(
        "app.services.user_provisioning.apply_workspace_acl",
        lambda commands: [AclCommandResult(commands[0], 0, "ok", "")],
    )

    result = UserProvisioningService(AppConfig()).provision(
        UserProvisioningRequest(
            ad_request=_ad_request(),
            operator_username=r"EXAMPLE\admin",
            operator_password="AdminPass1!",
            userfolder_root="users",
            scan_root="scan",
            onec_root="onec",
        )
    )

    assert calls["operator"] == (r"EXAMPLE\admin", "AdminPass1!")
    assert calls["mail_password"] == "UserPass1!"
    assert calls["mail_change_required"] is True
    assert result.mail is not None
    assert result.workspace is not None
    assert result.issues == []


def test_provisioning_continues_with_files_when_mail_fails(monkeypatch):
    org = YandexOrg("example", "Example", "example.ru", "42", "1", True, token="token")
    calls = {"workspace": False}

    monkeypatch.setattr(
        "app.services.user_provisioning.AdService.create_user",
        lambda self, request, **_kwargs: AdCreateUserResult(
            request.login,
            request.upn,
            "Иванов Иван Иванович",
            "CN=User,OU=Users",
        ),
    )
    monkeypatch.setattr("app.services.user_provisioning.load_yandex_orgs", lambda _path: [org])
    monkeypatch.setattr("app.services.user_provisioning.find_yandex_org", lambda _orgs, _domain: org)
    monkeypatch.setattr(
        "app.services.user_provisioning.create_yandex_user",
        lambda _org, _request: (_ for _ in ()).throw(RuntimeError("Yandex недоступен")),
    )

    def fake_workspace(**_kwargs):
        calls["workspace"] = True
        return _workspace()

    monkeypatch.setattr("app.services.user_provisioning.create_user_workspace", fake_workspace)
    monkeypatch.setattr("app.services.user_provisioning.build_workspace_acl_commands", lambda **_kwargs: [])
    monkeypatch.setattr("app.services.user_provisioning.apply_workspace_acl", lambda _commands: [])

    result = UserProvisioningService(AppConfig()).provision(
        UserProvisioningRequest(
            ad_request=_ad_request(),
            operator_username="admin",
            operator_password="secret",
            userfolder_root="users",
        )
    )

    assert calls["workspace"] is True
    assert result.workspace is not None
    assert result.mail is None
    assert [(issue.stage, issue.message) for issue in result.issues] == [
        ("Почта Yandex 360", "Yandex недоступен")
    ]
