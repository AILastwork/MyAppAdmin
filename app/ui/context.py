from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.audit import AuditLogger
from app.config import AppConfig


@dataclass(slots=True)
class PageContext:
    config: AppConfig
    audit: AuditLogger
    config_path: Path
    on_config_changed: Callable[[], None] | None = None

