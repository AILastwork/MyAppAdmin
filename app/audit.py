from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import getpass
import json
from pathlib import Path
import sqlite3
from typing import Any


SECRET_KEY_PARTS = ("password", "passwd", "secret", "token", "cookie", "authorization", "key")


@dataclass(slots=True)
class AuditRecord:
    created_at: str
    windows_user: str
    action: str
    object_type: str
    object_name: str
    result: str
    message: str
    params_json: str


class AuditLogger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    windows_user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_name TEXT NOT NULL,
                    result TEXT NOT NULL,
                    message TEXT NOT NULL,
                    params_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at)")

    def log(
        self,
        action: str,
        object_type: str = "",
        object_name: str = "",
        result: str = "INFO",
        message: str = "",
        params: dict[str, Any] | None = None,
    ) -> None:
        safe_params = sanitize_params(params or {})
        record = AuditRecord(
            created_at=datetime.now().isoformat(timespec="seconds"),
            windows_user=getpass.getuser(),
            action=action,
            object_type=object_type,
            object_name=object_name,
            result=result,
            message=message,
            params_json=json.dumps(safe_params, ensure_ascii=False, sort_keys=True),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (
                    created_at, windows_user, action, object_type,
                    object_name, result, message, params_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.created_at,
                    record.windows_user,
                    record.action,
                    record.object_type,
                    record.object_name,
                    record.result,
                    record.message,
                    record.params_json,
                ),
            )

    def recent(self, limit: int = 200) -> list[AuditRecord]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT created_at, windows_user, action, object_type,
                       object_name, result, message, params_json
                FROM audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [AuditRecord(*row) for row in rows]


def sanitize_params(value: Any) -> Any:
    """Маскирует секреты перед записью в аудит."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SECRET_KEY_PARTS):
                result[key] = "***"
            else:
                result[key] = sanitize_params(item)
        return result
    if isinstance(value, list):
        return [sanitize_params(item) for item in value]
    return value

