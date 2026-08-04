from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any


APP_NAME = "MyAppAdmin"
APP_DISPLAY_NAME = "MyAppAdmin"
DEFAULT_USER_1C_ROOT = r"\\osnova.local\fs\IBASE"
DEFAULT_SCAN_ACCOUNT = "scan_user.osnova.local"
DEFAULT_SHARED_ROOT = r"\\osnova.local\fs\IT\MyAppAdmin"
DEFAULT_TEMPLATE_DIR = DEFAULT_SHARED_ROOT
DEFAULT_YANDEX_TOKEN_FILE = DEFAULT_SHARED_ROOT + r"\API_yandex360.txt"
DEFAULT_PRINTER_CONFIG_FILE = DEFAULT_SHARED_ROOT + r"\printers.json"
DEFAULT_GLPI_BASE_URL = "http://glpi.osnova.local"
LEGACY_TEMPLATE_DIR = r"\\osnova.local\fs\ADM_SECURE\templates_1c"
LEGACY_YANDEX_TOKEN_FILE = r"\\osnova.local\fs\ADM_SECURE\yandex_api_tokens.txt"
LEGACY_PRINTER_CONFIG_FILE = r"\\osnova.local\fs\ADM_SECURE\printers.json"

SECRET_CONFIG_FIELDS = {
    "ad_read_password",
    "kyocera_admin_password",
    "kyocera_smb_password",
}
DEPRECATED_CONFIG_FIELDS = {
    "allowed_login_groups",
    "allowed_ous",
    "allowed_groups",
    "require_allowed_login_group",
    "denied_groups",
}
DPAPI_PREFIX = "dpapi:v1:"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def get_appdata_dir() -> Path:
    """Возвращает каталог настроек приложения в профиле текущего Windows-пользователя."""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / "AppData" / "Roaming" / APP_NAME


def default_config_path() -> Path:
    return get_appdata_dir() / "config.json"


def default_audit_db_path() -> Path:
    return get_appdata_dir() / "audit.db"


@dataclass(slots=True)
class AppConfig:
    domain: str = "OSNOVA"
    base_dn: str = "DC=osnova,DC=local"
    app_theme: str = "dark"
    ad_ldap_server: str = "osnova.local"
    ad_ldaps_port: str = "636"
    ad_read_user: str = ""
    ad_read_password: str = ""
    ad_search_limit: str = "50"
    ad_search_visible_columns: list[str] = field(default_factory=list)
    yandex_visible_columns: list[str] = field(default_factory=list)
    userfolder_root: str = r"\\osnova.local\fs\USERFOLDER"
    user_scan_root: str = r"\\osnova.local\fs\USERFOLDER"
    user_1c_root: str = DEFAULT_USER_1C_ROOT
    template_dir: str = DEFAULT_TEMPLATE_DIR
    yandex_token_file: str = DEFAULT_YANDEX_TOKEN_FILE
    printer_config_file: str = DEFAULT_PRINTER_CONFIG_FILE
    glpi_base_url: str = DEFAULT_GLPI_BASE_URL
    audit_db: str = field(default_factory=lambda: str(default_audit_db_path()))
    default_1c_profile: str = "default.v8i"
    scan_account: str = DEFAULT_SCAN_ACCOUNT
    service_mode_enabled: bool = False
    kyocera_script_path: str = "kyocera_add.py"
    kyocera_admin_login: str = "Admin"
    kyocera_admin_password: str = ""
    kyocera_smb_host: str = "osnova.local"
    kyocera_smb_port: str = "445"
    kyocera_smb_username: str = r"osnova.local\scan_user"
    kyocera_smb_password: str = ""
    kyocera_smb_base_path: str = r"fs\USERFOLDER"

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        config_path = path or default_config_path()
        if not config_path.exists():
            config = cls()
            config.save(config_path)
            return config

        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        normalized = cls._normalize_data(data)
        should_resave_secrets = any(_secret_needs_protection(data.get(key, "")) for key in SECRET_CONFIG_FIELDS)
        should_remove_deprecated = any(key in data for key in DEPRECATED_CONFIG_FIELDS)
        should_resave_defaults = any(
            normalized[key] != data.get(key)
            for key in (
                "user_1c_root",
                "scan_account",
                "template_dir",
                "yandex_token_file",
                "printer_config_file",
            )
        )
        for key in SECRET_CONFIG_FIELDS:
            normalized[key] = _unprotect_secret_from_storage(normalized.get(key, ""))
        config = cls(**normalized)
        if (should_resave_secrets or should_resave_defaults or should_remove_deprecated) and os.name == "nt":
            config.save(config_path)
        return config

    @staticmethod
    def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
        defaults = asdict(AppConfig())
        result: dict[str, Any] = {}
        for key, default_value in defaults.items():
            value = data.get(key, default_value)
            if isinstance(default_value, list):
                result[key] = _normalize_list(value)
            elif isinstance(default_value, bool):
                result[key] = _normalize_bool(value)
            else:
                result[key] = value
        onec_root = str(data.get("user_1c_root", "") or "").strip()
        userfolder_root = str(data.get("userfolder_root", defaults["userfolder_root"]) or "").strip()
        if not onec_root or onec_root.casefold() == userfolder_root.casefold():
            result["user_1c_root"] = DEFAULT_USER_1C_ROOT
        if str(data.get("scan_account", "") or "").strip().casefold() in {"", "scan_user"}:
            result["scan_account"] = DEFAULT_SCAN_ACCOUNT
        if str(data.get("template_dir", "") or "").strip().casefold() in {"", LEGACY_TEMPLATE_DIR.casefold()}:
            result["template_dir"] = DEFAULT_TEMPLATE_DIR
        if str(data.get("yandex_token_file", "") or "").strip().casefold() in {
            "",
            LEGACY_YANDEX_TOKEN_FILE.casefold(),
        }:
            result["yandex_token_file"] = DEFAULT_YANDEX_TOKEN_FILE
        if str(data.get("printer_config_file", "") or "").strip().casefold() in {
            "",
            LEGACY_PRINTER_CONFIG_FILE.casefold(),
        }:
            result["printer_config_file"] = DEFAULT_PRINTER_CONFIG_FILE
        return result

    def save(self, path: Path | None = None) -> Path:
        config_path = path or default_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        for key in SECRET_CONFIG_FIELDS:
            data[key] = _protect_secret_for_storage(data.get(key, ""))
        config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config_path

    def template_path(self, profile_name: str | None = None) -> Path:
        name = profile_name or self.default_1c_profile
        return Path(self.template_dir) / name


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.replace(";", "\n").splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "да", "on"}


def _protect_secret_for_storage(value: Any) -> str:
    text = str(value or "")
    if not text or text.startswith(DPAPI_PREFIX):
        return text
    return DPAPI_PREFIX + base64.b64encode(_dpapi_protect(text.encode("utf-8"))).decode("ascii")


def _secret_needs_protection(value: Any) -> bool:
    text = str(value or "")
    return bool(text and not text.startswith(DPAPI_PREFIX))


def _unprotect_secret_from_storage(value: Any) -> str:
    text = str(value or "")
    if not text.startswith(DPAPI_PREFIX):
        return text
    payload = text[len(DPAPI_PREFIX) :]
    try:
        encrypted = base64.b64decode(payload.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("Некорректное DPAPI-значение в config.json.") from exc
    return _dpapi_unprotect(encrypted).decode("utf-8")


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI-шифрование секретов доступно только в Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, _buffer = _blob_from_bytes(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        f"{APP_NAME} config secret",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI-расшифровка секретов доступна только в Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_blob, _buffer = _blob_from_bytes(data)
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer
