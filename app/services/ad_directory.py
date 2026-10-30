from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
import re
import ssl
import string
from typing import Any, Iterator

from app.config import AppConfig

try:
    from ldap3 import ALL, BASE, SUBTREE, MODIFY_ADD, MODIFY_REPLACE, Connection, Server, Tls
    from ldap3.utils.conv import escape_filter_chars
    from ldap3.utils.dn import escape_rdn
except ImportError:  # pragma: no cover - handled at runtime on target host
    ALL = BASE = SUBTREE = MODIFY_ADD = MODIFY_REPLACE = Connection = Server = Tls = None
    escape_filter_chars = None
    escape_rdn = None


LDAP_MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"
TOKEN_RE = re.compile(r"[\s,;]+")
NON_LOGIN_RE = re.compile(r"[^a-z0-9._-]+")
MAX_SAM_ACCOUNT_NAME = 20
PASSWORD_SPECIALS = "!@_"
DEFAULT_DOMAIN_ADMIN_GROUPS = [
    "Domain Admins",
    "Enterprise Admins",
    "Schema Admins",
    "Account Operators",
    "Administrators",
    "Администраторы домена",
    "Администраторы предприятия",
    "Администраторы схемы",
    "Операторы учета",
    "Операторы учётных записей",
    "Администраторы",
]

USER_SEARCH_ATTRIBUTES = [
    "sAMAccountName",
    "userPrincipalName",
    "displayName",
    "mail",
    "telephoneNumber",
    "department",
    "title",
    "company",
    "physicalDeliveryOfficeName",
    "description",
    "manager",
    "memberOf",
    "userAccountControl",
    "distinguishedName",
    "whenCreated",
    "lastLogonTimestamp",
]

TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


@dataclass(slots=True)
class AdUser:
    login: str
    name: str
    upn: str = ""
    mail: str = ""
    phone: str = ""
    department: str = ""
    title: str = ""
    company: str = ""
    office: str = ""
    description: str = ""
    manager: str = ""
    ou: str = ""
    dn: str = ""
    groups: list[str] = field(default_factory=list)
    created: str = ""
    last_activity: str = ""
    disabled: bool = False


@dataclass(slots=True)
class AdGroup:
    name: str
    account_name: str = ""
    dn: str = ""
    description: str = ""
    created: str = ""


@dataclass(slots=True)
class AdOrganizationalUnit:
    name: str
    dn: str
    description: str = ""
    created: str = ""


@dataclass(slots=True)
class LoginSuggestion:
    login: str
    checked: list[dict[str, Any]] = field(default_factory=list)
    verified_in_ad: bool = False
    warning: str = ""


def parse_full_name(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in (value or "").split() if part.strip()]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], " ".join(parts[2:])


def build_login_candidates(last_name: str, first_name: str, middle_name: str = "") -> list[str]:
    last = _translit(last_name)
    first = _translit(first_name)
    middle = _translit(middle_name)
    if not last or not first:
        return []

    candidates = [
        _short_login(f"{first[0]}.{last}"),
        _short_login(f"{first[0]}.{middle[0]}.{last}") if middle else "",
        _short_login(f"{first}.{last}"),
    ]
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def suggest_login(config: AppConfig, last_name: str, first_name: str, middle_name: str = "") -> LoginSuggestion:
    candidates = build_login_candidates(last_name, first_name, middle_name)
    if not candidates:
        return LoginSuggestion("", warning="Укажите фамилию и имя.")

    checked: list[dict[str, Any]] = []
    try:
        with read_connection(config) as conn:
            for candidate in candidates:
                exists = check_user_exists(conn, config, candidate)
                checked.append({"login": candidate, "exists": exists})
                if not exists:
                    return LoginSuggestion(candidate, checked=checked, verified_in_ad=True)

            stem = candidates[-1][: max(1, MAX_SAM_ACCOUNT_NAME - 4)].rstrip(".")
            for index in range(2, 1000):
                candidate = _short_login(f"{stem}{index}")
                exists = check_user_exists(conn, config, candidate)
                checked.append({"login": candidate, "exists": exists})
                if not exists:
                    return LoginSuggestion(candidate, checked=checked, verified_in_ad=True)
    except Exception as exc:
        return LoginSuggestion(candidates[0], checked=checked, verified_in_ad=False, warning=str(exc))

    return LoginSuggestion("", checked=checked, verified_in_ad=True, warning="Не удалось подобрать свободный login.")


def generate_password(length: int = 10) -> str:
    if length < 4:
        raise ValueError("Длина пароля должна быть не меньше 4.")
    rng = random.SystemRandom()
    required = [
        rng.choice(string.ascii_lowercase),
        rng.choice(string.ascii_uppercase),
        rng.choice(string.digits),
        rng.choice(PASSWORD_SPECIALS),
    ]
    alphabet = string.ascii_letters + string.digits + PASSWORD_SPECIALS
    required.extend(rng.choice(alphabet) for _ in range(length - len(required)))
    rng.shuffle(required)
    return "".join(required)


def search_users(config: AppConfig, query: str, limit: int | None = None) -> list[AdUser]:
    parts = _tokens(query)
    if not parts:
        raise ValueError("Введите login, ФИО, email, телефон или часть названия отдела.")

    per_part: list[str] = []
    for part in parts:
        safe = _safe_filter(part)
        per_part.append(
            f"(|(sAMAccountName=*{safe}*)(userPrincipalName=*{safe}*)(displayName=*{safe}*)"
            f"(givenName=*{safe}*)(sn=*{safe}*)(mail=*{safe}*)(telephoneNumber=*{safe}*)"
            f"(department=*{safe}*)(title=*{safe}*)(description=*{safe}*))"
        )
    search_filter = f"(&(objectCategory=user){''.join(per_part)})"

    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=USER_SEARCH_ATTRIBUTES,
            size_limit=_search_limit(config, limit),
        )
        items = [_user_from_entry(entry) for entry in conn.entries]

    normalized_query = query.strip().lower()
    items.sort(key=lambda item: (0 if item.login.lower() == normalized_query else 1, item.login.lower()))
    return items


def search_groups(config: AppConfig, query: str, limit: int | None = None) -> list[AdGroup]:
    parts = _tokens(query)
    if not parts:
        return []

    per_part: list[str] = []
    for part in parts:
        safe = _safe_filter(part)
        per_part.append(f"(|(cn=*{safe}*)(sAMAccountName=*{safe}*)(displayName=*{safe}*)(description=*{safe}*))")
    search_filter = f"(&(objectCategory=group){''.join(per_part)})"

    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=["cn", "sAMAccountName", "description", "distinguishedName", "whenCreated"],
            size_limit=_search_limit(config, limit),
        )
        items = [_group_from_entry(entry) for entry in conn.entries]

    normalized_query = query.strip().lower()
    items.sort(key=lambda item: (0 if item.name.lower() == normalized_query else 1, item.name.lower()))
    return items


def search_organizational_units(config: AppConfig, query: str, limit: int | None = None) -> list[AdOrganizationalUnit]:
    parts = _tokens(query)
    if not parts:
        return []

    per_part: list[str] = []
    for part in parts:
        safe = _safe_filter(part)
        per_part.append(f"(|(ou=*{safe}*)(name=*{safe}*)(description=*{safe}*)(distinguishedName=*{safe}*))")
    search_filter = f"(&(objectClass=organizationalUnit){''.join(per_part)})"

    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=["ou", "name", "description", "distinguishedName", "whenCreated"],
            size_limit=_search_limit(config, limit),
        )
        items = [_ou_from_entry(entry) for entry in conn.entries]

    normalized_query = query.strip().lower()
    items.sort(key=lambda item: (0 if item.name.lower() == normalized_query else 1, item.name.lower()))
    return items


def list_group_members(config: AppConfig, group_dn: str, limit: int | None = None) -> list[AdUser]:
    dn = (group_dn or "").strip()
    if not dn:
        raise ValueError("Не выбран DN группы.")
    safe_dn = _safe_filter(dn)
    search_filter = f"(&(objectCategory=user)(memberOf:{LDAP_MATCHING_RULE_IN_CHAIN}:={safe_dn}))"

    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=USER_SEARCH_ATTRIBUTES,
            size_limit=_search_limit(config, limit),
        )
        users = [_user_from_entry(entry) for entry in conn.entries]
    return sorted(users, key=lambda user: user.login.lower())


def list_ou_members(config: AppConfig, ou_dn: str, limit: int | None = None) -> list[AdUser]:
    dn = (ou_dn or "").strip()
    if not dn:
        raise ValueError("Не выбран DN OU.")

    with read_connection(config) as conn:
        conn.search(
            dn,
            "(objectCategory=user)",
            search_scope=SUBTREE,
            attributes=USER_SEARCH_ATTRIBUTES,
            size_limit=_search_limit(config, limit),
        )
        users = [_user_from_entry(entry) for entry in conn.entries]
    return sorted(users, key=lambda user: user.login.lower())


def list_organizational_units(config: AppConfig, query: str = "", limit: int = 1000) -> list[str]:
    safe = _safe_filter(query) if query else ""
    search_filter = f"(&(objectClass=organizationalUnit)(distinguishedName=*{safe}*))" if safe else "(objectClass=organizationalUnit)"
    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=["distinguishedName"],
            size_limit=_bounded_limit(limit, 2000),
        )
        values = [str(_entry_value(entry, "distinguishedName", entry.entry_dn)) for entry in conn.entries]
    return sorted({value for value in values if value}, key=str.lower)


def list_security_groups(config: AppConfig, query: str = "", limit: int = 1000) -> list[str]:
    safe = _safe_filter(query) if query else ""
    if safe:
        search_filter = f"(&(objectCategory=group)(|(cn=*{safe}*)(sAMAccountName=*{safe}*)(distinguishedName=*{safe}*)))"
    else:
        search_filter = "(objectCategory=group)"

    with read_connection(config) as conn:
        conn.search(
            _base_dn(config),
            search_filter,
            attributes=["cn", "sAMAccountName"],
            size_limit=_bounded_limit(limit, 2000),
        )
        values = [
            str(_entry_value(entry, "cn", "")) or str(_entry_value(entry, "sAMAccountName", ""))
            for entry in conn.entries
        ]
    return sorted({value for value in values if value}, key=str.lower)


def login_exists(config: AppConfig, login: str) -> bool:
    with read_connection(config) as conn:
        return check_user_exists(conn, config, login)


def set_user_enabled(config: AppConfig, user_dn: str, enabled: bool) -> None:
    dn = (user_dn or "").strip()
    if not dn:
        raise ValueError("Выберите пользователя AD.")

    with read_connection(config) as conn:
        user = _load_user_for_modify(conn, dn)
        current = int(_entry_value(user, "userAccountControl", 0) or 0)
        updated = current & ~2 if enabled else current | 2
        changes: dict[str, Any] = {"userAccountControl": [(MODIFY_REPLACE, [str(updated)])]}
        if enabled:
            changes["lockoutTime"] = [(MODIFY_REPLACE, ["0"])]
        if not conn.modify(dn, changes):
            raise ValueError(f"Не удалось изменить статус учетной записи AD: {conn.result}")


def change_user_password(config: AppConfig, user_dn: str, password: str, change_at_logon: bool = False) -> None:
    dn = (user_dn or "").strip()
    new_password = (password or "").strip()
    if not dn:
        raise ValueError("Выберите пользователя AD.")
    if not new_password:
        raise ValueError("Введите новый пароль.")

    with read_connection(config) as conn:
        _load_user_for_modify(conn, dn)
        if not conn.modify(dn, {"unicodePwd": [(MODIFY_REPLACE, [_encode_password(new_password)])]}):
            raise ValueError(f"Не удалось сменить пароль AD: {conn.result}")
        if change_at_logon:
            if not conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, ["0"])]}):
                raise ValueError(f"Пароль изменен, но не удалось поставить смену при входе: {conn.result}")


def check_user_exists(conn: Any, config: AppConfig, login: str) -> bool:
    safe = _safe_filter(login)
    conn.search(
        _base_dn(config),
        f"(&(objectCategory=user)(sAMAccountName={safe}))",
        attributes=["sAMAccountName"],
        size_limit=1,
    )
    return bool(conn.entries)


def resolve_group_dn(conn: Any, config: AppConfig, token: str) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    if "=" in value and "," in value:
        return value
    safe = _safe_filter(value)
    conn.search(
        _base_dn(config),
        f"(&(objectCategory=group)(|(cn={safe})(sAMAccountName={safe})(displayName={safe})))",
        attributes=["distinguishedName"],
        size_limit=1,
    )
    return str(conn.entries[0].entry_dn) if conn.entries else ""


def add_user_object(
    conn: Any,
    config: AppConfig,
    *,
    user_dn: str,
    login: str,
    upn: str,
    display_name: str,
    first_name: str,
    last_name: str,
    middle_name: str,
    title: str,
    password: str,
    change_password_at_logon: bool,
    group_dns: list[str],
) -> None:
    _require_ldap3()
    if check_user_exists(conn, config, login):
        raise ValueError(f"Login уже существует в AD: {login}")

    attrs: dict[str, Any] = {
        "objectClass": ["top", "person", "organizationalPerson", "user"],
        "cn": display_name,
        "sAMAccountName": login,
        "userPrincipalName": upn,
        "displayName": display_name,
        "givenName": first_name,
        "sn": last_name,
        "userAccountControl": 514,
    }
    if title:
        attrs["title"] = title
    if middle_name:
        attrs["middleName"] = middle_name
        attrs["initials"] = middle_name[0]

    if not conn.add(user_dn, attributes=attrs):
        raise ValueError(f"Не удалось создать пользователя AD: {conn.result}")

    if not conn.modify(user_dn, {"unicodePwd": [(MODIFY_REPLACE, [_encode_password(password)])]}):
        raise ValueError(f"Пользователь создан, но пароль не установлен: {conn.result}")

    pwd_last_set = "0" if change_password_at_logon else "-1"
    conn.modify(user_dn, {"pwdLastSet": [(MODIFY_REPLACE, [pwd_last_set])]})

    for group_dn in group_dns:
        if not conn.modify(group_dn, {"member": [(MODIFY_ADD, [user_dn])]}):
            raise ValueError(f"Не удалось добавить пользователя в группу {group_dn}: {conn.result}")

    if not conn.modify(user_dn, {"userAccountControl": [(MODIFY_REPLACE, ["512"])]}):
        raise ValueError(f"Пользователь создан, но не включен: {conn.result}")


@contextmanager
def read_connection(config: AppConfig) -> Iterator[Any]:
    _require_ldap3()
    bind_user = _normalize_bind_user(config.ad_read_user, config)
    password = config.ad_read_password or ""
    if not bind_user or not password:
        raise RuntimeError("Для AD-поиска заполните настройки ad_read_user и ad_read_password.")

    conn = Connection(_server(config), user=bind_user, password=password, auto_bind=True)
    try:
        yield conn
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def verify_ad_admin_credentials(config: AppConfig, username: str, password: str) -> str:
    with authorized_admin_connection(config, username, password) as (_conn, user_dn):
        return user_dn


@contextmanager
def authorized_admin_connection(config: AppConfig, username: str, password: str) -> Iterator[tuple[Any, str]]:
    _require_ldap3()
    bind_user = _normalize_bind_user(username, config)
    if not bind_user or not password:
        raise PermissionError("Введите учетную запись и пароль доменного администратора AD.")

    conn = Connection(_server(config), user=bind_user, password=password, auto_bind=True)
    try:
        user_dn = _find_bound_user_dn(conn, config, username, bind_user)
        admin_groups = _unique_group_tokens(DEFAULT_DOMAIN_ADMIN_GROUPS)
        for group in admin_groups:
            if _user_in_group_chain(conn, config, user_dn, group):
                yield conn, user_dn
                return
        raise PermissionError(
            "Учетная запись успешно прошла bind в AD, но не состоит в стандартной "
            "администраторской группе домена."
        )
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def _server(config: AppConfig) -> Any:
    host = (config.ad_ldap_server or "").strip() or _domain_suffix(config)
    if not host:
        raise RuntimeError("Не задан ad_ldap_server.")
    port = int(str(config.ad_ldaps_port or "636").strip() or "636")
    return Server(host, port=port, use_ssl=True, tls=_tls(config), get_info=ALL, connect_timeout=8)


def _tls(config: AppConfig) -> Any:
    if not config.ad_tls_verify:
        return Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLS_CLIENT)
    # Без ca_certs_file ldap3 берёт системное хранилище (load_default_certs),
    # куда на доменной машине групповой политикой уже раздан корневой ЦС AD.
    ca_file = (config.ad_tls_ca_file or "").strip() or None
    return Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT, ca_certs_file=ca_file)


def _find_bound_user_dn(conn: Any, config: AppConfig, username: str, bind_user: str) -> str:
    raw = (username or bind_user or "").strip()
    candidates = {raw, bind_user}
    if "\\" in raw:
        candidates.add(raw.split("\\", 1)[1])
    if "@" in raw:
        candidates.add(raw.split("@", 1)[0])

    filters = []
    for candidate in candidates:
        safe = _safe_filter(candidate)
        if not safe:
            continue
        filters.append(f"(sAMAccountName={safe})")
        filters.append(f"(userPrincipalName={safe})")

    if not filters:
        raise PermissionError("Не удалось определить login администратора AD.")

    conn.search(
        _base_dn(config),
        f"(&(objectCategory=user)(|{''.join(filters)}))",
        attributes=["distinguishedName"],
        size_limit=1,
    )
    if not conn.entries:
        raise PermissionError("Учетная запись администратора не найдена в AD.")
    return str(conn.entries[0].entry_dn)


def _user_in_group_chain(conn: Any, config: AppConfig, user_dn: str, group: str) -> bool:
    token = _group_token(group)
    if not token:
        return False
    safe_group = _safe_filter(token)
    safe_user_dn = _safe_filter(user_dn)
    if group.strip().lower().startswith("cn="):
        group_match = f"(distinguishedName={_safe_filter(group)})"
    else:
        group_match = f"(|(cn={safe_group})(sAMAccountName={safe_group}))"
    conn.search(
        _base_dn(config),
        f"(&(objectCategory=group){group_match}(member:{LDAP_MATCHING_RULE_IN_CHAIN}:={safe_user_dn}))",
        attributes=["cn"],
        size_limit=1,
    )
    return bool(conn.entries)


def _group_token(group: str) -> str:
    value = (group or "").strip()
    if not value:
        return ""
    if value.lower().startswith("cn="):
        return value
    return value.rsplit("\\", 1)[-1]


def _unique_group_tokens(groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        token = _group_token(group).strip().lower()
        if token and token not in seen:
            seen.add(token)
            result.append(group)
    return result


def _require_ldap3() -> None:
    if Connection is None:
        raise RuntimeError("Не установлен пакет ldap3. Выполните: python -m pip install -e .[dev]")


def _base_dn(config: AppConfig) -> str:
    value = (config.base_dn or "").strip()
    if value:
        return value
    suffix = _domain_suffix(config)
    if suffix:
        return ",".join(f"DC={part}" for part in suffix.split(".") if part)
    raise RuntimeError("Не задан base_dn.")


def _domain_suffix(config: AppConfig) -> str:
    parts: list[str] = []
    for item in (config.base_dn or "").split(","):
        item = item.strip()
        if item.upper().startswith("DC="):
            parts.append(item[3:])
    if parts:
        return ".".join(parts).lower()
    domain = (config.domain or "").strip().lower()
    return domain if "." in domain else ""


def upn_suffix(config: AppConfig) -> str:
    suffix = _domain_suffix(config)
    if suffix:
        return suffix
    raise RuntimeError("Не удалось определить UPN suffix из base_dn/domain.")


def safe_rdn(value: str) -> str:
    _require_ldap3()
    return escape_rdn(str(value or "").strip())


def _normalize_bind_user(username: str, config: AppConfig) -> str:
    value = (username or "").strip()
    if not value:
        return ""
    if "@" in value:
        return value
    if "\\" in value:
        domain, login = value.split("\\", 1)
        suffix = _domain_suffix(config)
        if suffix and domain.lower() == (config.domain or "").lower():
            return f"{login}@{suffix}"
        return value
    suffix = _domain_suffix(config)
    return f"{value}@{suffix}" if suffix else value


def _tokens(text: str, max_len: int = 48) -> list[str]:
    return [item.strip()[:max_len] for item in TOKEN_RE.split(text or "") if item.strip()]


def _safe_filter(value: str) -> str:
    _require_ldap3()
    return escape_filter_chars(str(value or "").strip())


def _encode_password(password: str) -> bytes:
    return f'"{password}"'.encode("utf-16-le")


def _entry_value(entry: Any, name: str, default: Any = "") -> Any:
    try:
        value = entry[name].value
    except Exception:
        return default
    return default if value is None else value


def _entry_values(entry: Any, name: str) -> list[str]:
    try:
        values = entry[name].values
    except Exception:
        return []
    return [str(value) for value in values if value]


def _load_user_for_modify(conn: Any, user_dn: str) -> Any:
    conn.search(
        user_dn,
        "(objectClass=user)",
        search_scope=BASE,
        attributes=["sAMAccountName", "userAccountControl"],
        size_limit=1,
    )
    if not conn.entries:
        raise ValueError(f"Пользователь AD не найден: {user_dn}")
    return conn.entries[0]


def _user_from_entry(entry: Any) -> AdUser:
    user_account_control = int(_entry_value(entry, "userAccountControl", 0) or 0)
    dn = str(entry.entry_dn)
    return AdUser(
        login=str(_entry_value(entry, "sAMAccountName", "")),
        upn=str(_entry_value(entry, "userPrincipalName", "")),
        name=str(_entry_value(entry, "displayName", "")),
        mail=str(_entry_value(entry, "mail", "")),
        phone=str(_entry_value(entry, "telephoneNumber", "")),
        department=str(_entry_value(entry, "department", "")),
        title=str(_entry_value(entry, "title", "")),
        company=str(_entry_value(entry, "company", "")),
        office=str(_entry_value(entry, "physicalDeliveryOfficeName", "")),
        description=str(_entry_value(entry, "description", "")),
        manager=_cn_from_dn(str(_entry_value(entry, "manager", ""))),
        ou=_ou_path(dn),
        dn=dn,
        groups=sorted(_cn_from_dn(group_dn) for group_dn in _entry_values(entry, "memberOf")),
        created=format_ad_datetime(_entry_value(entry, "whenCreated", "")),
        last_activity=format_ad_filetime(_entry_value(entry, "lastLogonTimestamp", "")),
        disabled=bool(user_account_control & 2),
    )


def _group_from_entry(entry: Any) -> AdGroup:
    return AdGroup(
        name=str(_entry_value(entry, "cn", "")),
        account_name=str(_entry_value(entry, "sAMAccountName", "")),
        dn=str(_entry_value(entry, "distinguishedName", entry.entry_dn)),
        description=str(_entry_value(entry, "description", "")),
        created=format_ad_datetime(_entry_value(entry, "whenCreated", "")),
    )


def _ou_from_entry(entry: Any) -> AdOrganizationalUnit:
    dn = str(_entry_value(entry, "distinguishedName", entry.entry_dn))
    name = str(_entry_value(entry, "ou", "")) or str(_entry_value(entry, "name", "")) or _cn_from_dn(dn)
    return AdOrganizationalUnit(
        name=name,
        dn=dn,
        description=str(_entry_value(entry, "description", "")),
        created=format_ad_datetime(_entry_value(entry, "whenCreated", "")),
    )


def format_ad_datetime(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        moment = value
        if moment.tzinfo:
            moment = moment.astimezone()
        return moment.strftime("%d.%m.%Y %H:%M")

    text = str(value).strip()
    if not text:
        return ""
    for fmt in ("%Y%m%d%H%M%S.%fZ", "%Y%m%d%H%M%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")
        except ValueError:
            pass
    normalized = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(normalized)
    except ValueError:
        return text[:19]
    if moment.tzinfo:
        moment = moment.astimezone()
    return moment.strftime("%d.%m.%Y %H:%M")


def format_ad_filetime(value: Any) -> str:
    try:
        raw = int(str(value or "0"))
    except (TypeError, ValueError):
        raw = 0
    if raw <= 0:
        return "нет данных"
    unix_seconds = (raw - 116444736000000000) / 10_000_000
    try:
        return datetime.fromtimestamp(unix_seconds, timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M")
    except (OverflowError, OSError, ValueError):
        return "нет данных"


def _cn_from_dn(dn: str) -> str:
    match = re.match(r"^CN=([^,]+)", dn or "")
    return match.group(1).replace("\\,", ",") if match else dn


def _ou_path(dn: str) -> str:
    parts: list[str] = []
    for item in re.split(r"(?<!\\),", dn or ""):
        if item.upper().startswith(("OU=", "CN=")):
            parts.append(item.split("=", 1)[1].replace("\\,", ","))
    parts.reverse()
    return " / ".join(parts)


def _search_limit(config: AppConfig, limit: int | None) -> int:
    raw = limit if limit is not None else config.ad_search_limit
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 300))


def _bounded_limit(value: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = maximum
    return max(1, min(parsed, maximum))


def _translit(text: str) -> str:
    result = "".join(TRANSLIT.get(ch, ch) for ch in (text or "").strip().lower())
    result = re.sub(r"[^a-z0-9.]+", "", result)
    return re.sub(r"\.+", ".", result).strip(".")


def _short_login(value: str) -> str:
    value = NON_LOGIN_RE.sub("", (value or "").lower())
    value = re.sub(r"[._-]+", ".", value).strip(".")
    return value[:MAX_SAM_ACCOUNT_NAME].strip(".")
