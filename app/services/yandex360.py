from __future__ import annotations

import configparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import requests


ORG_LINE_RE = re.compile(r"^ORG_ID\s*=\s*(?P<org_id>\d+)(?:\s+(?P<domain>[A-Za-z0-9.-]+))?\s*$", re.IGNORECASE)
YANDEX_API_BASE_URL = "https://api360.yandex.net"


@dataclass(slots=True)
class YandexOrg:
    key: str
    name: str
    domain: str
    org_id: str
    department_id: str
    has_token: bool
    token: str = ""


@dataclass(slots=True)
class YandexUser:
    id: str
    nickname: str
    email: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    middle_name: str = ""
    position: str = ""
    is_admin: bool = False
    is_dismissed: bool = False
    is_enabled: bool = False
    created_at: str = ""
    updated_at: str = ""
    enabled_updated_at: str = ""


@dataclass(slots=True)
class YandexCreateUserRequest:
    nickname: str
    password: str
    first_name: str
    last_name: str
    middle_name: str = ""
    position: str = ""
    department_id: str = ""
    password_change_required: bool = True


class YandexApiError(RuntimeError):
    pass


def load_yandex_orgs(token_file: str | Path) -> list[YandexOrg]:
    path = Path(token_file)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []

    if _looks_like_ini(text):
        return _load_ini_orgs(text)

    return _load_legacy_orgs(text)


def _looks_like_ini(text: str) -> bool:
    return any(line.strip().startswith("[") for line in text.splitlines())


def _load_ini_orgs(text: str) -> list[YandexOrg]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    orgs: list[YandexOrg] = []
    for section in parser.sections():
        data = parser[section]
        orgs.append(
            YandexOrg(
                key=section,
                name=data.get("name", section),
                domain=data.get("domain", ""),
                org_id=data.get("org_id", ""),
                department_id=data.get("department_id", "1"),
                has_token=bool(data.get("token", "")),
                token=data.get("token", "").strip(),
            )
        )
    return orgs


def _load_legacy_orgs(text: str) -> list[YandexOrg]:
    orgs: list[YandexOrg] = []
    pending: tuple[str, str] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = ORG_LINE_RE.match(line)
        if match:
            if pending:
                orgs.append(_legacy_org(*pending, token=""))
            org_id = match.group("org_id")
            domain = (match.group("domain") or "").lower()
            pending = (org_id, domain)
            continue

        if pending:
            org_id, domain = pending
            orgs.append(_legacy_org(org_id, domain, token=line))
            pending = None

    if pending:
        orgs.append(_legacy_org(*pending, token=""))

    return orgs


def _legacy_org(org_id: str, domain: str, token: str) -> YandexOrg:
    key = domain or org_id
    return YandexOrg(
        key=key,
        name=domain or key,
        domain=domain,
        org_id=org_id,
        department_id="1",
        has_token=bool(token.strip()),
        token=token.strip(),
    )


def list_yandex_users(org: YandexOrg, query: str = "", limit: int = 500) -> list[YandexUser]:
    users: list[YandexUser] = []
    page = 1
    per_page = min(max(limit, 1), 100)
    while len(users) < limit:
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if "@" in query:
            params["email"] = query.strip()
        payload = _yandex_request("GET", f"/directory/v1/org/{org.org_id}/users", org, params=params)
        raw_users = payload.get("users") or payload.get("items") or []
        page_users = [_user_from_payload(item) for item in raw_users]
        users.extend(page_users)
        pages = _safe_int(payload.get("pages"), default=page)
        if page >= pages or not page_users:
            break
        page += 1

    query_text = query.strip().lower()
    if query_text and "@" not in query_text:
        users = [
            user
            for user in users
            if query_text in user.nickname.lower()
            or query_text in user.email.lower()
            or query_text in user.display_name.lower()
        ]
    return users[:limit]


def create_yandex_user(org: YandexOrg, request: YandexCreateUserRequest) -> YandexUser:
    nickname = request.nickname.strip()
    password = request.password.strip()
    if not nickname:
        raise ValueError("Укажите login пользователя Yandex 360.")
    if not password:
        raise ValueError("Укажите пароль пользователя Yandex 360.")

    department_id = request.department_id.strip() or org.department_id or "1"
    body: dict[str, Any] = {
        "nickname": nickname,
        "departmentId": _safe_int(department_id, default=1),
        "name": {
            "first": request.first_name.strip(),
            "last": request.last_name.strip(),
            "middle": request.middle_name.strip(),
        },
        "position": request.position.strip(),
        "password": password,
        "passwordChangeRequired": request.password_change_required,
        "displayName": " ".join(
            part for part in [request.last_name.strip(), request.first_name.strip(), request.middle_name.strip()] if part
        ),
    }
    payload = _yandex_request("POST", f"/directory/v1/org/{org.org_id}/users", org, json=body)
    return _user_from_payload(_payload_user(payload))


def set_yandex_user_enabled(org: YandexOrg, user_id: str, enabled: bool) -> YandexUser:
    if not user_id.strip():
        raise ValueError("Выберите пользователя Yandex 360.")
    payload = _yandex_request(
        "PATCH",
        f"/directory/v1/org/{org.org_id}/users/{user_id.strip()}",
        org,
        json={"isEnabled": enabled},
    )
    return _user_from_payload(_payload_user(payload))


def find_yandex_org(orgs: list[YandexOrg], domain_or_key: str) -> YandexOrg:
    target = domain_or_key.strip().lower()
    for org in orgs:
        if target in {org.key.lower(), org.domain.lower(), org.org_id.lower()}:
            return org
    raise ValueError(f"Организация Yandex 360 не найдена: {domain_or_key}")


def format_datetime(value: str, empty_text: str = "нет данных") -> str:
    moment = _parse_iso_datetime(value)
    if not moment:
        return empty_text
    return moment.astimezone().strftime("%d.%m.%Y %H:%M")


def _yandex_request(
    method: str,
    path: str,
    org: YandexOrg,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not org.org_id:
        raise YandexApiError("Не задан org_id Yandex 360.")
    if not org.token:
        raise YandexApiError("Для организации Yandex 360 нет OAuth token.")

    url = f"{YANDEX_API_BASE_URL}{path}"
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"OAuth {org.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params=params,
        json=json,
        timeout=20,
    )
    if response.status_code >= 400:
        raise YandexApiError(_error_message(response))
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise YandexApiError(f"Yandex 360 вернул не JSON-ответ: HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise YandexApiError("Yandex 360 вернул неожиданный формат ответа.")
    return payload


def _user_from_payload(data: dict[str, Any]) -> YandexUser:
    name = data.get("name") if isinstance(data.get("name"), dict) else {}
    first = str(name.get("first", "") or "")
    last = str(name.get("last", "") or "")
    middle = str(name.get("middle", "") or "")
    display_name = str(data.get("displayName") or " ".join(part for part in [last, first, middle] if part))
    return YandexUser(
        id=str(data.get("id", "") or ""),
        nickname=str(data.get("nickname", "") or ""),
        email=str(data.get("email", "") or ""),
        display_name=display_name,
        first_name=first,
        last_name=last,
        middle_name=middle,
        position=str(data.get("position", "") or ""),
        is_admin=bool(data.get("isAdmin", False)),
        is_dismissed=bool(data.get("isDismissed", False)),
        is_enabled=bool(data.get("isEnabled", False)),
        created_at=str(data.get("createdAt", "") or ""),
        updated_at=str(data.get("updatedAt", "") or ""),
        enabled_updated_at=str(data.get("isEnabledUpdatedAt", "") or ""),
    )


def _payload_user(payload: dict[str, Any]) -> dict[str, Any]:
    user = payload.get("user")
    return user if isinstance(user, dict) else payload


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Yandex 360 API: HTTP {response.status_code}: {response.text[:300]}"
    message = payload.get("message") if isinstance(payload, dict) else ""
    return f"Yandex 360 API: HTTP {response.status_code}: {message or payload}"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
