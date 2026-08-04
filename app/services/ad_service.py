from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.config import AppConfig
from app.services.ad_directory import BASE, add_user_object, authorized_admin_connection, resolve_group_dn, safe_rdn, upn_suffix
from app.services.user_files import validate_login


LOGIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,19}$")
IMMUTABLE_ADMIN_GROUP_NAMES = {
    "account operators",
    "administrators",
    "backup operators",
    "cert publishers",
    "cloneable domain controllers",
    "cryptographic operators",
    "dnsadmins",
    "domain admins",
    "domain controllers",
    "enterprise admins",
    "enterprise key admins",
    "exchange organization administrators",
    "exchange servers",
    "exchange trusted subsystem",
    "exchange windows permissions",
    "group policy creator owners",
    "hyper-v administrators",
    "incoming forest trust builders",
    "key admins",
    "network configuration operators",
    "organization management",
    "print operators",
    "read-only domain controllers",
    "recipient management",
    "replicator",
    "schema admins",
    "server operators",
    "storage replica administrators",
    "администраторы",
    "администраторы dns",
    "администраторы hyper-v",
    "администраторы домена",
    "администраторы ключей",
    "администраторы ключей предприятия",
    "администраторы предприятия",
    "администраторы реплики хранилища",
    "администраторы схемы",
    "издатели сертификатов",
    "клонируемые контроллеры домена",
    "контроллеры домена",
    "контроллеры домена только для чтения",
    "операторы архива",
    "операторы настройки сети",
    "операторы печати",
    "операторы сервера",
    "операторы криптографии",
    "операторы учета",
    "операторы учётных записей",
    "репликатор",
    "создатели-владельцы групповой политики",
}
IMMUTABLE_ADMIN_GROUP_SIDS = {
    "S-1-5-32-544",
    "S-1-5-32-548",
    "S-1-5-32-549",
    "S-1-5-32-550",
    "S-1-5-32-551",
    "S-1-5-32-552",
    "S-1-5-32-556",
    "S-1-5-32-569",
    "S-1-5-32-580",
}
IMMUTABLE_ADMIN_DOMAIN_RIDS = {
    "498",
    "512",
    "516",
    "518",
    "519",
    "520",
    "521",
    "526",
    "527",
}
ADMIN_GROUP_NAME_MARKERS = ("admin", "администратор")


@dataclass(slots=True)
class AdCreateUserRequest:
    last_name: str
    first_name: str
    middle_name: str
    login: str
    password: str
    upn: str
    ou_dn: str
    title: str = ""
    groups: list[str] = field(default_factory=list)
    change_password_at_logon: bool = True
    create_yandex_mail: bool = False
    mail_domain: str = ""
    mail_password: str = ""


@dataclass(slots=True)
class AdOperationPlan:
    title: str
    steps: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdCreateUserResult:
    login: str
    upn: str
    display_name: str
    dn: str
    groups: list[str] = field(default_factory=list)


class AdService:
    """Сервис подготовки и выполнения AD-операций через LDAPS."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build_create_user_plan(self, request: AdCreateUserRequest) -> AdOperationPlan:
        self._validate_request_basics(request)
        blocking = self._validate_group_policy(request.groups)
        if blocking:
            raise ValueError("\n".join(blocking))
        fio = " ".join(part for part in [request.last_name, request.first_name, request.middle_name] if part)
        steps = [
            f"Проверить уникальность login: {request.login}",
            f"Создать AD-пользователя disabled: {fio}",
            f"Установить UPN: {request.upn}",
            f"Назначить OU: {request.ou_dn}",
            "Установить первичный пароль из поля формы",
            "Включить пользователя после успешной настройки",
        ]
        if request.groups:
            steps.append("Добавить в группы: " + ", ".join(request.groups))
        if request.change_password_at_logon:
            steps.append("Поставить смену пароля при первом входе")
        if request.create_yandex_mail:
            domain = request.mail_domain or request.upn.split("@", 1)[-1]
            steps.append(f"Создать почту Yandex 360: {request.login}@{domain}")
            if request.mail_password and request.mail_password != request.password:
                steps.append("Использовать отдельный первичный пароль почты Yandex 360")
            else:
                steps.append("Использовать пароль AD как первичный пароль почты Yandex 360")
        return AdOperationPlan("Создание AD-пользователя", steps)

    def create_user(
        self,
        request: AdCreateUserRequest,
        *,
        operator_username: str,
        operator_password: str,
    ) -> AdCreateUserResult:
        self._validate_request_basics(request)
        blocking = self._validate_group_policy(request.groups)
        if blocking:
            raise ValueError("\n".join(blocking))
        if not operator_username.strip() or not operator_password:
            raise PermissionError("Для создания пользователя нужен повторный ввод учетной записи и пароля администратора AD.")

        display_name = " ".join(part for part in [request.last_name, request.first_name, request.middle_name] if part).strip()
        upn = request.upn or f"{request.login}@{upn_suffix(self.config)}"
        user_dn = f"CN={safe_rdn(display_name)},{request.ou_dn}"

        with authorized_admin_connection(self.config, operator_username, operator_password) as (conn, _operator_dn):
            group_dns = self._resolve_and_validate_group_dns(conn, request.groups)
            add_user_object(
                conn,
                self.config,
                user_dn=user_dn,
                login=request.login,
                upn=upn,
                display_name=display_name,
                first_name=request.first_name,
                last_name=request.last_name,
                middle_name=request.middle_name,
                title=request.title,
                password=request.password,
                change_password_at_logon=request.change_password_at_logon,
                group_dns=group_dns,
            )

        return AdCreateUserResult(
            login=request.login,
            upn=upn,
            display_name=display_name,
            dn=user_dn,
            groups=list(request.groups),
        )

    def _validate_request_basics(self, request: AdCreateUserRequest) -> None:
        validate_login(request.login)
        if not LOGIN_RE.match(request.login):
            raise ValueError("Login AD должен начинаться с буквы/цифры и содержать до 20 символов: a-z, 0-9, точка, дефис, подчёркивание.")
        if not request.last_name or not request.first_name:
            raise ValueError("Укажите фамилию и имя.")
        if not request.password:
            raise ValueError("Укажите пароль.")
        if not request.ou_dn:
            raise ValueError("Выберите OU.")
        if not request.upn:
            raise ValueError("Укажите UPN / email.")

    def group_policy_error(self, group: str) -> str:
        normalized = self._norm_group(group)
        if self._looks_administrative_group_name(normalized):
            return f"Добавление в административную группу запрещено: {group}"
        return ""

    def _validate_group_policy(self, groups: list[str]) -> list[str]:
        errors: list[str] = []
        for group in groups:
            error = self.group_policy_error(group)
            if error:
                errors.append(error)
        return errors

    def _resolve_and_validate_group_dns(self, conn, groups: list[str]) -> list[str]:
        result: list[str] = []
        for group in groups:
            group_dn = resolve_group_dn(conn, self.config, group)
            if not group_dn:
                raise ValueError(f"Группа не найдена в AD: {group}")
            protected_group = self._protected_group_in_chain(conn, group_dn)
            if protected_group:
                raise ValueError(
                    f"Добавление в административную группу запрещено: {group}. "
                    f"Защищенная группа в цепочке членства: {protected_group}"
                )
            if group_dn not in result:
                result.append(group_dn)
        return result

    def _protected_group_in_chain(self, conn, group_dn: str) -> str:
        pending = [group_dn]
        visited: set[str] = set()
        while pending:
            current_dn = pending.pop(0)
            normalized_dn = current_dn.casefold()
            if normalized_dn in visited:
                continue
            visited.add(normalized_dn)

            conn.search(
                current_dn,
                "(objectClass=group)",
                search_scope=BASE,
                attributes=[
                    "cn",
                    "sAMAccountName",
                    "objectSid",
                    "adminCount",
                    "memberOf",
                ],
                size_limit=1,
            )
            if not conn.entries:
                raise ValueError(f"Не удалось проверить безопасность группы AD: {current_dn}")
            entry = conn.entries[0]
            name = str(
                self._entry_value(entry, "sAMAccountName")
                or self._entry_value(entry, "cn")
                or current_dn
            )
            sid = str(self._entry_value(entry, "objectSid")).upper()
            admin_count = str(self._entry_value(entry, "adminCount")).strip()
            if (
                self._looks_administrative_group_name(self._norm_group(name))
                or sid in IMMUTABLE_ADMIN_GROUP_SIDS
                or sid.rsplit("-", 1)[-1] in IMMUTABLE_ADMIN_DOMAIN_RIDS
                or admin_count == "1"
            ):
                return f"{name} ({sid or current_dn})"
            pending.extend(self._entry_values(entry, "memberOf"))
        return ""

    @staticmethod
    def _looks_administrative_group_name(normalized_name: str) -> bool:
        return (
            normalized_name in IMMUTABLE_ADMIN_GROUP_NAMES
            or any(marker in normalized_name for marker in ADMIN_GROUP_NAME_MARKERS)
        )

    @staticmethod
    def _entry_value(entry, name: str):
        try:
            value = entry[name].value
        except Exception:
            return ""
        return "" if value is None else value

    @staticmethod
    def _entry_values(entry, name: str) -> list[str]:
        try:
            values = entry[name].values
        except Exception:
            return []
        return [str(value) for value in values if value]

    def _norm_group(self, value: str) -> str:
        text = (value or "").strip().lower()
        if text.startswith("cn="):
            return text.split(",", 1)[0][3:]
        return text.rsplit("\\", 1)[-1]
