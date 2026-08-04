from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import os
from pathlib import Path
import subprocess

from app.security import current_windows_groups, hidden_subprocess_kwargs


@dataclass(slots=True)
class AclCommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def build_workspace_acl_commands(
    user_dir: str | Path,
    scan_dir: str | Path,
    login: str,
    domain: str,
    scan_account: str,
    onec_dir: str | Path | None = None,
    domain_admins_group: str = "Domain Admins",
) -> list[list[str]]:
    user_path = str(Path(user_dir))
    scan_path = str(Path(scan_dir))
    onec_path = str(Path(onec_dir)) if onec_dir else user_path
    user_principal = f"{domain}\\{login}" if domain else login
    admins_principal = resolve_domain_admins_principal(domain, domain_admins_group)
    scan_principal = normalize_acl_account(scan_account, domain)

    commands: list[list[str]] = []
    protected_paths: list[str] = []

    def protect_path(path: str, grants: list[str]) -> None:
        normalized = path.rstrip("\\/")
        if normalized.lower() in {item.lower() for item in protected_paths}:
            return
        protected_paths.append(normalized)
        commands.append(["icacls", path, "/grant:r", *grants])
        commands.append(["icacls", path, "/inheritance:r"])

    # Команды строятся отдельно, чтобы UI мог показать dry-run перед применением ACL.
    base_grants = [f"{user_principal}:(OI)(CI)F", f"{admins_principal}:(OI)(CI)F"]
    protect_path(user_path, base_grants)
    protect_path(onec_path, base_grants)
    scan_grants = list(base_grants)
    if scan_principal:
        scan_grants.append(f"{scan_principal}:(OI)(CI)M")
    protect_path(scan_path, scan_grants)

    return commands


def build_scan_acl_commands(
    scan_dir: str | Path,
    login: str,
    domain: str,
    scan_account: str,
    domain_admins_group: str = "Domain Admins",
) -> list[list[str]]:
    scan_path = str(Path(scan_dir))
    user_principal = f"{domain}\\{login}" if domain else login
    admins_principal = resolve_domain_admins_principal(domain, domain_admins_group)
    grants = [
        f"{user_principal}:(OI)(CI)F",
        f"{admins_principal}:(OI)(CI)F",
    ]
    scan_principal = normalize_acl_account(scan_account, domain)
    if scan_principal:
        grants.append(f"{scan_principal}:(OI)(CI)M")
    return [
        ["icacls", scan_path, "/grant:r", *grants],
        ["icacls", scan_path, "/inheritance:r"],
    ]


def apply_workspace_acl(commands: list[list[str]]) -> list[AclCommandResult]:
    results: list[AclCommandResult] = []
    failed_grant_paths: set[str] = set()
    for command in commands:
        path_key = command[1].rstrip("\\/").lower() if len(command) > 1 else ""
        if "/inheritance:r" in command and path_key in failed_grant_paths:
            results.append(
                AclCommandResult(
                    command=command,
                    returncode=1,
                    stdout="",
                    stderr="Отключение наследования пропущено: сначала не удалось назначить права.",
                )
            )
            continue

        completed = subprocess.run(command, capture_output=True, check=False, **hidden_subprocess_kwargs())
        stdout = _decode_icacls_output(completed.stdout)
        stderr = _decode_icacls_output(completed.stderr)
        if "/grant:r" in command and completed.returncode != 0:
            failed_grant_paths.add(path_key)
        results.append(
            AclCommandResult(
                command=command,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        )
    return results


def resolve_domain_admins_principal(domain: str, fallback_group: str = "Domain Admins") -> str:
    for group in current_windows_groups():
        normalized = group.strip()
        if normalized.lower().startswith("s-1-") and normalized.rsplit("-", 1)[-1] == "512":
            return f"*{normalized}"

    user_sid = _current_windows_user_sid()
    user_domain = os.environ.get("USERDOMAIN", "")
    if user_sid and domain and user_domain.lower() == domain.lower():
        return f"*{user_sid.rsplit('-', 1)[0]}-512"

    return f"{domain}\\{fallback_group}" if domain else fallback_group


def normalize_acl_account(account: str, domain: str) -> str:
    value = (account or "").strip()
    if not value or not domain or "\\" in value or "@" in value:
        return value

    dotted_domain_suffix = f".{domain.lower()}.local"
    if value.lower().endswith(dotted_domain_suffix):
        username = value[: -len(dotted_domain_suffix)].rstrip(".")
        if username:
            return f"{domain}\\{username}"
    return value


def _current_windows_user_sid() -> str:
    try:
        completed = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            timeout=6,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""

    text = _decode_command_output(completed.stdout)
    try:
        row = next(csv.reader(io.StringIO(text)), [])
    except csv.Error:
        return ""
    return row[1].strip() if len(row) >= 2 and row[1].strip().lower().startswith("s-1-") else ""


def _decode_icacls_output(value: bytes | str | None) -> str:
    return _decode_command_output(value, encodings=("cp866", "utf-8-sig", "cp1251"))


def _decode_command_output(
    value: bytes | str | None,
    *,
    encodings: tuple[str, ...] = ("utf-8-sig", "cp866", "cp1251"),
) -> str:
    if isinstance(value, str):
        return value
    if not value:
        return ""
    for encoding in encodings:
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode(encodings[0], errors="replace")
