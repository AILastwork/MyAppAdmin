from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.config import AppConfig
from app.services.acl import AclCommandResult, apply_workspace_acl, build_workspace_acl_commands
from app.services.ad_service import AdCreateUserRequest, AdCreateUserResult, AdService
from app.services.user_files import UserWorkspaceResult, create_user_workspace
from app.services.yandex360 import (
    YandexCreateUserRequest,
    YandexUser,
    create_yandex_user,
    find_yandex_org,
    load_yandex_orgs,
)


ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class UserProvisioningRequest:
    ad_request: AdCreateUserRequest
    operator_username: str
    operator_password: str
    create_files: bool = True
    userfolder_root: str = ""
    scan_root: str = ""
    onec_root: str = ""
    template_path: Path | None = None
    overwrite_v8i: bool = False


@dataclass(slots=True)
class ProvisioningIssue:
    stage: str
    message: str


@dataclass(slots=True)
class UserProvisioningResult:
    ad: AdCreateUserResult
    mail: YandexUser | None = None
    workspace: UserWorkspaceResult | None = None
    acl_results: list[AclCommandResult] = field(default_factory=list)
    issues: list[ProvisioningIssue] = field(default_factory=list)


class UserProvisioningService:
    """Единый сценарий создания AD, почты, папок 1C и ACL."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def provision(
        self,
        request: UserProvisioningRequest,
        progress: ProgressCallback | None = None,
    ) -> UserProvisioningResult:
        ad_request = request.ad_request
        total = 1 + int(ad_request.create_yandex_mail) + int(request.create_files) * 2
        current = 1
        self._progress(progress, current, total, "Создаю учетную запись Active Directory...")
        ad_result = AdService(self.config).create_user(
            ad_request,
            operator_username=request.operator_username,
            operator_password=request.operator_password,
        )
        result = UserProvisioningResult(ad=ad_result)

        if ad_request.create_yandex_mail:
            current += 1
            self._progress(progress, current, total, "Создаю почту Yandex 360...")
            try:
                org = find_yandex_org(
                    load_yandex_orgs(self.config.yandex_token_file),
                    ad_request.mail_domain,
                )
                result.mail = create_yandex_user(
                    org,
                    YandexCreateUserRequest(
                        nickname=ad_request.login,
                        password=ad_request.mail_password or ad_request.password,
                        first_name=ad_request.first_name,
                        last_name=ad_request.last_name,
                        middle_name=ad_request.middle_name,
                        position=ad_request.title,
                        department_id=org.department_id,
                        password_change_required=ad_request.change_password_at_logon,
                    ),
                )
            except Exception as exc:
                result.issues.append(ProvisioningIssue("Почта Yandex 360", str(exc)))

        if request.create_files:
            current += 1
            self._progress(progress, current, total, "Создаю папки и файлы 1C...")
            try:
                result.workspace = create_user_workspace(
                    login=ad_request.login,
                    userfolder_root=request.userfolder_root,
                    scan_root=request.scan_root or None,
                    onec_root=request.onec_root or None,
                    template_path=request.template_path,
                    overwrite_v8i=request.overwrite_v8i,
                    overwrite_start_cfg=True,
                )
            except Exception as exc:
                result.issues.append(ProvisioningIssue("Папки и файлы 1C", str(exc)))

            current += 1
            self._progress(progress, current, total, "Назначаю права на папки...")
            if result.workspace:
                commands = build_workspace_acl_commands(
                    user_dir=result.workspace.user_dir,
                    scan_dir=result.workspace.scan_dir,
                    onec_dir=result.workspace.onec_dir,
                    login=ad_request.login,
                    domain=self.config.domain,
                    scan_account=self.config.scan_account,
                )
                try:
                    result.acl_results = apply_workspace_acl(commands)
                    failed = [item for item in result.acl_results if item.returncode != 0]
                    if failed:
                        details = "\n".join(
                            (item.stderr or item.stdout or " ".join(item.command)).strip()
                            for item in failed[-5:]
                        )
                        result.issues.append(ProvisioningIssue("ACL папок", details))
                except Exception as exc:
                    result.issues.append(ProvisioningIssue("ACL папок", str(exc)))
            else:
                result.issues.append(
                    ProvisioningIssue("ACL папок", "Права не применены, потому что папки не были созданы.")
                )

        self._progress(progress, total, total, "Готово")
        return result

    @staticmethod
    def _progress(
        callback: ProgressCallback | None,
        current: int,
        total: int,
        status: str,
    ) -> None:
        if callback:
            callback(current, total, status)
