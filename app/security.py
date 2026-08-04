from __future__ import annotations

from dataclasses import dataclass
import getpass
import locale
import os
from pathlib import Path
import subprocess

from app.config import AppConfig


@dataclass(slots=True)
class SecurityStatus:
    windows_user: str
    domain: str
    service_mode_enabled: bool
    userfolder_available: bool
    template_dir_available: bool
    yandex_token_file_available: bool
    printer_config_file_available: bool


def current_windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def collect_security_status(config: AppConfig) -> SecurityStatus:
    """Показывает стартовую картину доступности, без выполнения опасных операций."""
    return SecurityStatus(
        windows_user=current_windows_user(),
        domain=config.domain,
        service_mode_enabled=config.service_mode_enabled,
        userfolder_available=_exists(config.userfolder_root),
        template_dir_available=_exists(config.template_dir),
        yandex_token_file_available=_exists(config.yandex_token_file),
        printer_config_file_available=_exists(config.printer_config_file),
    )


def _exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def current_windows_groups() -> list[str]:
    try:
        completed = subprocess.run(
            ["whoami", "/groups", "/fo", "csv", "/nh"],
            capture_output=True,
            timeout=6,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []

    groups: list[str] = []
    for raw_line in _decode_command_output(completed.stdout).splitlines():
        parts = _parse_whoami_csv_line(raw_line)
        if parts:
            group_name = parts[0].strip()
            if group_name:
                groups.append(group_name)
            if len(parts) >= 3:
                group_sid = parts[2].strip()
                if group_sid:
                    groups.append(group_sid)
    return sorted(set(groups), key=str.lower)


def hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags} if flags else {}


def is_current_user_domain_admin(groups: list[str] | None = None) -> bool:
    current_groups = current_windows_groups() if groups is None else groups
    for group in current_groups:
        normalized = group.strip()
        lowered = normalized.casefold()
        if lowered.endswith(r"\domain admins") or lowered.endswith(r"\администраторы домена"):
            return True
        if lowered.startswith("s-1-") and lowered.rsplit("-", 1)[-1] == "512":
            return True
    return False


def _decode_command_output(value: bytes | str | None) -> str:
    if isinstance(value, str):
        return value
    if not value:
        return ""

    encodings = ["utf-8-sig", locale.getpreferredencoding(False), "cp866"]
    for encoding in dict.fromkeys(encodings):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _parse_whoami_csv_line(line: str) -> list[str]:
    # Формат whoami /groups /fo csv стабилен, но без csv-модуля проще не терять
    # производительность старта приложения.
    result: list[str] = []
    current = ""
    in_quotes = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                current += '"'
                index += 1
            else:
                in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            result.append(current)
            current = ""
        else:
            current += char
        index += 1
    result.append(current)
    return result
