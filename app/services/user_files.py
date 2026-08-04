from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.services import v8i


LOGIN_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(slots=True)
class UserWorkspaceResult:
    login: str
    user_dir: Path
    scan_dir: Path
    onec_dir: Path
    ibases_path: Path
    start_cfg_path: Path
    created_user_dir: bool
    created_scan_dir: bool
    created_onec_dir: bool
    wrote_ibases: bool
    wrote_start_cfg: bool


def create_user_workspace(
    login: str,
    userfolder_root: str | Path,
    scan_root: str | Path | None = None,
    onec_root: str | Path | None = None,
    template_path: str | Path | None = None,
    overwrite_v8i: bool = False,
    overwrite_start_cfg: bool = True,
) -> UserWorkspaceResult:
    safe_login = validate_login(login)
    user_dir = Path(userfolder_root) / safe_login
    scan_dir = (Path(scan_root) / safe_login / "scan") if scan_root else user_dir / "scan"
    onec_dir = (Path(onec_root) / safe_login) if onec_root else user_dir
    ibases_path = onec_dir / "ibases.v8i"
    start_cfg_path = onec_dir / "1CEStart.cfg"

    user_existed = user_dir.exists()
    scan_existed = scan_dir.exists()
    onec_existed = onec_dir.exists()
    user_dir.mkdir(parents=True, exist_ok=True)
    scan_dir.mkdir(parents=True, exist_ok=True)
    onec_dir.mkdir(parents=True, exist_ok=True)

    if template_path:
        wrote_ibases = v8i.copy_template_v8i(template_path, ibases_path, overwrite=overwrite_v8i)
    else:
        wrote_ibases = v8i.create_empty_v8i(ibases_path, overwrite=overwrite_v8i)
    wrote_start_cfg = v8i.create_1cestart_cfg(start_cfg_path, ibases_path, overwrite=overwrite_start_cfg)

    return UserWorkspaceResult(
        login=safe_login,
        user_dir=user_dir,
        scan_dir=scan_dir,
        onec_dir=onec_dir,
        ibases_path=ibases_path,
        start_cfg_path=start_cfg_path,
        created_user_dir=not user_existed,
        created_scan_dir=not scan_existed,
        created_onec_dir=not onec_existed,
        wrote_ibases=wrote_ibases,
        wrote_start_cfg=wrote_start_cfg,
    )


def validate_login(login: str) -> str:
    value = login.strip()
    if not LOGIN_RE.match(value):
        raise ValueError("Login может содержать только латиницу, цифры, точку, подчёркивание и дефис.")
    if value in {".", ".."}:
        raise ValueError("Некорректный login для имени папки.")
    return value
