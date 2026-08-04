from __future__ import annotations

from dataclasses import asdict, dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Protocol
import json
from uuid import uuid4


@dataclass(slots=True)
class PrinterDevice:
    name: str
    vendor: str
    model: str
    host: str
    location: str = ""
    credentials_ref: str = ""


@dataclass(slots=True)
class PrinterAddressBookEntry:
    full_name: str
    login: str
    email: str
    scan_path: str
    smb_login: str = ""


class PrinterAdapter(Protocol):
    vendor: str

    def build_preview(self, device: PrinterDevice, entry: PrinterAddressBookEntry) -> list[str]:
        ...


def load_printer_devices(config_file: str | Path) -> list[PrinterDevice]:
    path = Path(config_file)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        devices = data.get("devices", [])
    elif isinstance(data, list):
        devices = data
    else:
        devices = []
    return [
        PrinterDevice(
            name=str(item.get("name", "")),
            vendor=str(item.get("vendor", "")),
            model=str(item.get("model", "")),
            host=str(item.get("host", "")),
            location=str(item.get("location", "")),
            credentials_ref=str(item.get("credentials_ref", "")),
        )
        for item in devices
    ]


def merge_printer_devices(*device_lists: list[PrinterDevice]) -> list[PrinterDevice]:
    result: list[PrinterDevice] = []
    seen_hosts: set[str] = set()
    for devices in device_lists:
        for device in devices:
            key = device.host.strip().lower()
            if key and key in seen_hosts:
                continue
            if key:
                seen_hosts.add(key)
            result.append(device)
    return result


def add_printer_device(
    config_file: str | Path,
    host: str,
    *,
    name: str = "",
    vendor: str = "Kyocera",
    model: str = "",
    location: str = "",
    credentials_ref: str = "kyocera_default",
) -> PrinterDevice:
    normalized_host = normalize_printer_ip(host)
    path = Path(config_file)
    data: dict | list
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, (dict, list)):
            raise ValueError("printers.json должен содержать объект с devices или массив устройств.")
    else:
        data = {"devices": []}

    if isinstance(data, dict):
        devices = data.setdefault("devices", [])
        if not isinstance(devices, list):
            raise ValueError("Поле devices в printers.json должно быть массивом.")
    else:
        devices = data

    for item in devices:
        if isinstance(item, dict) and str(item.get("host", "")).strip().lower() == normalized_host.lower():
            raise ValueError(f"Принтер с IP {normalized_host} уже существует.")

    device = PrinterDevice(
        name=name.strip() or f"{vendor.strip() or 'Принтер'} {normalized_host}",
        vendor=vendor.strip() or "Kyocera",
        model=model.strip(),
        host=normalized_host,
        location=location.strip(),
        credentials_ref=credentials_ref.strip(),
    )
    devices.append(asdict(device))
    _write_printer_config(path, data)
    return device


def remove_printer_device(config_file: str | Path, host: str) -> bool:
    path = Path(config_file)
    if not path.exists():
        return False

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        devices = data.get("devices", [])
        if not isinstance(devices, list):
            raise ValueError("Поле devices в printers.json должно быть массивом.")
    elif isinstance(data, list):
        devices = data
    else:
        raise ValueError("printers.json должен содержать объект с devices или массив устройств.")

    normalized_host = (host or "").strip().lower()
    if not normalized_host:
        return False

    original_count = len(devices)
    devices[:] = [
        item
        for item in devices
        if not (
            isinstance(item, dict)
            and str(item.get("host", "")).strip().lower() == normalized_host
        )
    ]
    if len(devices) == original_count:
        return False

    _write_printer_config(path, data)
    return True


def normalize_printer_ip(value: str) -> str:
    host = (value or "").strip()
    if not host:
        raise ValueError("Укажите IP-адрес принтера.")
    try:
        return str(ip_address(host))
    except ValueError as exc:
        raise ValueError(f"Некорректный IP-адрес принтера: {host}") from exc


def _write_printer_config(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
