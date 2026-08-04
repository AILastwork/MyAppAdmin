from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil


DEFAULT_IBASES_FILENAME = "ibases.v8i"


@dataclass(slots=True)
class V8iBase:
    name: str
    fields: dict[str, str] = field(default_factory=dict)

    def server(self) -> str:
        return _extract_connect_value(self.fields.get("Connect", ""), "Srvr")

    def ref(self) -> str:
        return _extract_connect_value(self.fields.get("Connect", ""), "Ref")

    def client(self) -> str:
        return self.fields.get("ClientConnectionSpeed", "")

    def version(self) -> str:
        return self.fields.get("App", "") or self.fields.get("Version", "")


def normalize_ibases_path(path: str | Path) -> Path:
    raw = str(path).strip()
    if not raw:
        raise ValueError("Укажите путь к ibases.v8i.")

    filepath = Path(raw)
    if raw.endswith(("\\", "/")):
        return filepath / DEFAULT_IBASES_FILENAME

    try:
        if filepath.exists() and filepath.is_dir():
            return filepath / DEFAULT_IBASES_FILENAME
    except OSError:
        pass

    if filepath.suffix == "" and filepath.name.lower() != DEFAULT_IBASES_FILENAME:
        return filepath / DEFAULT_IBASES_FILENAME
    return filepath


def parse_v8i(path: str | Path) -> list[V8iBase]:
    filepath = normalize_ibases_path(path)
    if not filepath.exists():
        return []
    if filepath.is_dir():
        raise IsADirectoryError(f"Укажите файл {DEFAULT_IBASES_FILENAME}, а не папку: {filepath}")

    bases: list[V8iBase] = []
    current_name: str | None = None
    current_fields: dict[str, str] = {}

    for raw_line in filepath.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            if current_name is not None:
                bases.append(V8iBase(current_name, current_fields))
                current_name = None
                current_fields = {}
            continue
        if line.startswith("[") and line.endswith("]"):
            if current_name is not None:
                bases.append(V8iBase(current_name, current_fields))
                current_fields = {}
            current_name = line[1:-1].strip()
            continue
        if "=" in line and current_name is not None:
            key, value = line.split("=", 1)
            current_fields[key.strip()] = value.strip()

    if current_name is not None:
        bases.append(V8iBase(current_name, current_fields))
    return bases


def write_v8i(bases: list[V8iBase], path: str | Path) -> None:
    filepath = normalize_ibases_path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(serialize_v8i(bases), encoding="utf-8-sig")


def serialize_v8i(bases: list[V8iBase]) -> str:
    lines: list[str] = []
    for base in bases:
        lines.append(f"[{base.name or 'Unnamed'}]")
        for key, value in base.fields.items():
            lines.append(f"{key}={value}")
        lines.append("")
    return "\n".join(lines)


def copy_template_v8i(template_path: str | Path, dest_path: str | Path, overwrite: bool = False) -> bool:
    src = Path(template_path)
    dest = normalize_ibases_path(dest_path)
    if not src.exists():
        raise FileNotFoundError(f"Шаблон V8i не найден: {src}")
    if dest.exists() and not overwrite:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def create_empty_v8i(dest_path: str | Path, overwrite: bool = False) -> bool:
    dest = normalize_ibases_path(dest_path)
    if dest.exists() and not overwrite:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("", encoding="utf-8-sig")
    return True


def build_1cestart_cfg(ibases_path: str | Path, include_section: bool = True) -> str:
    lines: list[str] = []
    if include_section:
        lines.append("[COMMON]")
    lines.append("UseHWLicenses=0")
    lines.append(f"CommonInfoBases={ibases_path}")
    return "\n".join(lines) + "\n"


def create_1cestart_cfg(dest_path: str | Path, ibases_path: str | Path, overwrite: bool = True) -> bool:
    dest = Path(dest_path)
    if dest.exists() and not overwrite:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(build_1cestart_cfg(ibases_path), encoding="utf-8")
    return True


def list_template_profiles(template_dir: str | Path) -> list[Path]:
    directory = Path(template_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.v8i"), key=lambda item: item.name.lower())


def normalize_template_filename(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("Укажите имя файла шаблона, например default.v8i.")
    if Path(value).name != value:
        raise ValueError("Имя шаблона должно быть именем файла без пути.")
    if Path(value).suffix.lower() != ".v8i":
        value = f"{value}.v8i"
    return value


def rename_template_profile(path: str | Path, new_name: str) -> Path:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Шаблон V8i не найден: {source}")
    target = source.with_name(normalize_template_filename(new_name))
    if target == source:
        return source
    if target.exists():
        raise FileExistsError(f"Шаблон с таким именем уже существует: {target.name}")
    source.rename(target)
    return target


def _extract_connect_value(connect: str, key: str) -> str:
    quoted_marker = f'{key}="'
    quoted_start = connect.find(quoted_marker)
    if quoted_start != -1:
        quoted_start += len(quoted_marker)
        quoted_end = connect.find('"', quoted_start)
        return connect[quoted_start:quoted_end] if quoted_end != -1 else ""

    marker = f"{key}="
    start = connect.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = connect.find(";", start)
    return connect[start:end] if end != -1 else connect[start:]
