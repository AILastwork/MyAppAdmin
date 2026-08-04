from __future__ import annotations

import io
import json
from threading import Event

import pytest

from app.config import AppConfig
from app.services.printers.base import (
    PrinterAddressBookEntry,
    PrinterDevice,
    add_printer_device,
    load_printer_devices,
    merge_printer_devices,
    normalize_printer_ip,
    remove_printer_device,
)
from app.services.printers.kyocera import (
    KYOCERA_ADAPTED_MODELS,
    KYOCERA_OPERATION_TIMEOUT_SECONDS,
    KYOCERA_WORKER_FLAG,
    KyoceraAdapter,
    KyoceraOperationCancelled,
    _kyocera_runner,
    _stream_process_output,
    provision_scan_folder,
    scan_folder_exists,
)


def test_add_printer_device_by_ip_preserves_object_format(tmp_path):
    path = tmp_path / "printers.json"
    path.write_text(
        json.dumps(
            {
                "site": "main",
                "devices": [
                    {
                        "name": "Existing",
                        "vendor": "Kyocera",
                        "model": "",
                        "host": "192.168.10.20",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    added = add_printer_device(path, "192.168.10.25", name="Kyocera ресепшен")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert added.host == "192.168.10.25"
    assert added.name == "Kyocera ресепшен"
    assert data["site"] == "main"
    assert len(load_printer_devices(path)) == 2


def test_add_printer_device_preserves_list_format(tmp_path):
    path = tmp_path / "printers.json"
    path.write_text("[]", encoding="utf-8")

    add_printer_device(path, "10.0.0.15")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["host"] == "10.0.0.15"


def test_add_printer_device_rejects_invalid_or_duplicate_ip(tmp_path):
    path = tmp_path / "printers.json"
    add_printer_device(path, "192.168.1.10")

    with pytest.raises(ValueError, match="уже существует"):
        add_printer_device(path, "192.168.1.10")
    with pytest.raises(ValueError, match="Некорректный IP"):
        normalize_printer_ip("printer.local")


def test_remove_printer_device_preserves_json_shape(tmp_path):
    object_path = tmp_path / "printers-object.json"
    object_path.write_text(
        json.dumps(
            {
                "site": "main",
                "devices": [
                    {"name": "Old", "vendor": "Kyocera", "model": "", "host": "192.168.10.20"},
                    {"name": "Keep", "vendor": "Kyocera", "model": "", "host": "192.168.10.30"},
                ],
            }
        ),
        encoding="utf-8",
    )
    list_path = tmp_path / "printers-list.json"
    list_path.write_text(
        json.dumps(
            [
                {"name": "Old", "vendor": "Kyocera", "model": "", "host": "10.0.0.15"},
                {"name": "Keep", "vendor": "Kyocera", "model": "", "host": "10.0.0.16"},
            ]
        ),
        encoding="utf-8",
    )

    assert remove_printer_device(object_path, "192.168.10.20")
    assert remove_printer_device(list_path, "10.0.0.15")
    assert not remove_printer_device(list_path, "10.0.0.99")

    object_data = json.loads(object_path.read_text(encoding="utf-8"))
    list_data = json.loads(list_path.read_text(encoding="utf-8"))
    assert object_data["site"] == "main"
    assert [item["host"] for item in object_data["devices"]] == ["192.168.10.30"]
    assert isinstance(list_data, list)
    assert [item["host"] for item in list_data] == ["10.0.0.16"]


def test_merge_printer_devices_prefers_shared_entry_for_duplicate_host():
    shared = [PrinterDevice("Общий", "Kyocera", "", "192.168.1.10")]
    local = [
        PrinterDevice("Локальный дубль", "Kyocera", "", "192.168.1.10"),
        PrinterDevice("Локальный", "Kyocera", "", "192.168.1.20"),
    ]

    merged = merge_printer_devices(shared, local)

    assert [(device.name, device.host) for device in merged] == [
        ("Общий", "192.168.1.10"),
        ("Локальный", "192.168.1.20"),
    ]


def test_provision_scan_folder_creates_directory_and_applies_scan_acl(monkeypatch, tmp_path):
    scan_path = tmp_path / "users" / "i.ivanov" / "scan"
    entry = PrinterAddressBookEntry(
        full_name="Иванов Иван Иванович",
        login="i.ivanov",
        email="i.ivanov@mkd-osnova.ru",
        scan_path=str(scan_path),
    )
    commands = [["icacls", str(scan_path), "/grant:r", "OSNOVA\\i.ivanov:(OI)(CI)F"]]
    applied: list[list[list[str]]] = []
    monkeypatch.setattr(
        "app.services.printers.kyocera.build_scan_acl_commands",
        lambda **_kwargs: commands,
    )
    monkeypatch.setattr(
        "app.services.printers.kyocera.apply_workspace_acl",
        lambda value: applied.append(value) or [],
    )

    result = provision_scan_folder(entry, AppConfig())

    assert scan_folder_exists(scan_path)
    assert result.path == scan_path
    assert applied == [commands]


def test_frozen_kyocera_runner_uses_embedded_worker(monkeypatch, tmp_path):
    executable = tmp_path / "MyAppAdmin.exe"
    monkeypatch.setattr("app.services.printers.kyocera.sys.frozen", True, raising=False)
    monkeypatch.setattr("app.services.printers.kyocera.sys.executable", str(executable))

    command, working_directory = _kyocera_runner(AppConfig())

    assert command == [str(executable), KYOCERA_WORKER_FLAG]
    assert working_directory == tmp_path


def test_kyocera_adapter_streams_sanitized_output(monkeypatch, tmp_path):
    script_path = tmp_path / "kyocera_add.py"
    script_path.write_text("", encoding="utf-8")
    config = AppConfig(
        kyocera_script_path=str(script_path),
        kyocera_admin_password="admin-secret",
        kyocera_smb_password="smb-secret",
    )

    class FakeProcess:
        def __init__(self):
            self.stdout = io.StringIO(
                "[KYOCERA] Подключение admin-secret\n"
                "[KYOCERA] Контакт принят, пароль smb-secret скрыт\n"
            )

        def poll(self):
            return 0

        def wait(self):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(
        "app.services.printers.kyocera.subprocess.Popen",
        lambda *_args, **_kwargs: FakeProcess(),
    )
    streamed: list[str] = []

    result = KyoceraAdapter().add_entry(
        PrinterDevice("KM1E33BC", "Kyocera", "ECOSYS MA4500x", "10.14.32.47"),
        PrinterAddressBookEntry(
            "Иванов Иван",
            "i.ivanov",
            "i.ivanov@mkd-osnova.ru",
            r"\\osnova.local\fs\USERFOLDER\i.ivanov\scan",
        ),
        config,
        on_output=streamed.append,
    )

    assert result.returncode == 0
    assert streamed == result.output
    assert all("admin-secret" not in line and "smb-secret" not in line for line in streamed)
    assert all("******" in line for line in streamed)
    assert "ECOSYS MA4500x" in KYOCERA_ADAPTED_MODELS
    assert "ECOSYS M2040dn" in KYOCERA_ADAPTED_MODELS
    assert "ECOSYS M2135dn" in KYOCERA_ADAPTED_MODELS
    assert KYOCERA_OPERATION_TIMEOUT_SECONDS == 180


def test_kyocera_stream_cancellation_terminates_child_process(monkeypatch):
    class FakeProcess:
        stdout = io.StringIO("")

        def poll(self):
            return None

    process = FakeProcess()
    cancel_event = Event()
    cancel_event.set()
    terminated = []
    monkeypatch.setattr(
        "app.services.printers.kyocera._terminate_process_tree",
        lambda value: terminated.append(value),
    )

    with pytest.raises(KyoceraOperationCancelled):
        _stream_process_output(
            process,
            AppConfig(),
            60,
            None,
            cancel_event=cancel_event,
        )

    assert terminated == [process]
