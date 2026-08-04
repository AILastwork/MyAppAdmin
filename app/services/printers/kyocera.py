from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Event, Thread
import time
from typing import Callable

from app.config import AppConfig
from app.services.acl import AclCommandResult, apply_workspace_acl, build_scan_acl_commands
from app.services.printers.base import PrinterAddressBookEntry, PrinterDevice


KYOCERA_VERIFIED_MODELS = ("ECOSYS M3145dn", "ECOSYS M3540idn")
KYOCERA_ADAPTED_MODELS = ("ECOSYS MA4500x", "ECOSYS M2040dn", "ECOSYS M2135dn")
KYOCERA_WORKER_FLAG = "--kyocera-worker"
KYOCERA_OPERATION_TIMEOUT_SECONDS = 180
KYOCERA_COMPATIBILITY_NOTE = (
    "Скрипт проверен на Kyocera ECOSYS M3145dn и ECOSYS M3540idn. "
    "Диагностический цикл авторизации и формы подтверждён на ECOSYS MA4500x, "
    "M2040dn и M2135dn; для MA4500x поддерживается автоматический переход на HTTPS. "
    "Другие модели с Command Center RX могут работать, но требуют отдельной проверки прошивки."
)


@dataclass(slots=True)
class KyoceraRunResult:
    returncode: int
    output: list[str]


@dataclass(slots=True)
class ScanFolderProvisionResult:
    path: Path
    acl_results: list[AclCommandResult]


class KyoceraOperationCancelled(RuntimeError):
    pass


def scan_folder_exists(path: str | Path) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def provision_scan_folder(
    entry: PrinterAddressBookEntry,
    config: AppConfig,
) -> ScanFolderProvisionResult:
    scan_path = Path(entry.scan_path)
    scan_path.mkdir(parents=True, exist_ok=True)
    commands = build_scan_acl_commands(
        scan_dir=scan_path,
        login=entry.login,
        domain=config.domain,
        scan_account=config.scan_account,
    )
    return ScanFolderProvisionResult(
        path=scan_path,
        acl_results=apply_workspace_acl(commands),
    )


class KyoceraAdapter:
    vendor = "Kyocera"

    def build_preview(self, device: PrinterDevice, entry: PrinterAddressBookEntry) -> list[str]:
        smb_host, smb_base_path = _smb_host_and_base_path(entry.scan_path)
        return [
            f"Подключиться к Kyocera: {device.host}",
            f"Модель / имя: {device.model or 'не указана'} / {device.name}",
            f"Создать/обновить запись адресной книги: {entry.full_name}",
            f"SMB путь сканирования: {entry.scan_path}",
            f"SMB host/base: {smb_host} / {smb_base_path}",
            "Не выводить и не логировать пароль МФУ.",
        ]

    def add_entry(
        self,
        device: PrinterDevice,
        entry: PrinterAddressBookEntry,
        config: AppConfig,
        timeout: int = KYOCERA_OPERATION_TIMEOUT_SECONDS,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> KyoceraRunResult:
        runner, working_directory = _kyocera_runner(config)

        if not config.kyocera_admin_password:
            raise ValueError("Заполните kyocera_admin_password в настройках.")
        if not config.kyocera_smb_password:
            raise ValueError("Заполните kyocera_smb_password в настройках.")

        derived_host, derived_base_path = _smb_host_and_base_path(entry.scan_path)
        smb_host = config.kyocera_smb_host.strip() or derived_host
        smb_base_path = config.kyocera_smb_base_path.strip("\\/") or derived_base_path

        args = [
            *runner,
            "--printer",
            _printer_url(device.host),
            "--admin-login",
            config.kyocera_admin_login,
            "--admin-password",
            config.kyocera_admin_password,
            "--full-name",
            entry.full_name,
            "--login",
            entry.login,
            "--email",
            entry.email,
            "--smb-host",
            smb_host,
            "--smb-port",
            config.kyocera_smb_port,
            "--smb-username",
            config.kyocera_smb_username or entry.smb_login,
            "--smb-password",
            config.kyocera_smb_password,
            "--smb-base-path",
            smb_base_path,
            "--smb-scan-subfolder",
            "scan",
        ]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            args,
            cwd=working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            bufsize=1,
            creationflags=creationflags,
        )
        output = _stream_process_output(
            process,
            config,
            timeout,
            on_output,
            cancel_event=cancel_event,
        )
        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError("\n".join(output[-40:]) or f"kyocera_add.py завершился с кодом {returncode}")
        return KyoceraRunResult(returncode, output)


def _stream_process_output(
    process: subprocess.Popen[str],
    config: AppConfig,
    timeout: int,
    on_output: Callable[[str], None] | None,
    *,
    cancel_event: Event | None = None,
) -> list[str]:
    queue: Queue[str | None] = Queue()

    def read_output() -> None:
        stream = process.stdout
        if stream is not None:
            for raw_line in iter(stream.readline, ""):
                queue.put(raw_line)
            stream.close()
        queue.put(None)

    reader = Thread(target=read_output, daemon=True)
    reader.start()
    output: list[str] = []
    started_at = time.monotonic()
    stream_closed = False

    while not stream_closed or process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_process_tree(process)
            raise KyoceraOperationCancelled("Операция Kyocera отменена пользователем.")
        if time.monotonic() - started_at > timeout:
            _terminate_process_tree(process)
            raise TimeoutError(f"Операция Kyocera превысила таймаут {timeout} секунд.")
        try:
            raw_line = queue.get(timeout=0.1)
        except Empty:
            continue
        if raw_line is None:
            stream_closed = True
            continue
        for line in _safe_lines(raw_line, config):
            output.append(line)
            if on_output:
                on_output(line)

    reader.join(timeout=1)
    return output


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _kyocera_runner(config: AppConfig) -> tuple[list[str], Path]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return [str(executable), KYOCERA_WORKER_FLAG], executable.parent

    script_path = _resolve_script_path(config.kyocera_script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"Скрипт Kyocera не найден: {script_path}")
    return [sys.executable, str(script_path)], script_path.parent


def run_kyocera_worker(arguments: list[str]) -> int:
    _restore_worker_streams()
    import kyocera_add

    original_argv = sys.argv
    sys.argv = ["kyocera_add.py", *arguments]
    try:
        return kyocera_add.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        sys.argv = original_argv


def _restore_worker_streams() -> None:
    if sys.stdout is None:
        sys.stdout = _open_standard_stream(1)
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = _open_standard_stream(2)
    elif hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _open_standard_stream(file_descriptor: int):
    try:
        return os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            errors="replace",
            buffering=1,
            closefd=False,
        )
    except OSError:
        return open(os.devnull, "w", encoding="utf-8")


def _resolve_script_path(value: str) -> Path:
    path = Path(value or "kyocera_add.py")
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[3] / path


def _printer_url(host: str) -> str:
    value = host.strip()
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    return f"http://{value}".rstrip("/")


def _smb_host_and_base_path(scan_path: str) -> tuple[str, str]:
    value = scan_path.strip()
    if value.startswith("\\\\"):
        parts = [part for part in value.strip("\\").split("\\") if part]
        if len(parts) >= 2:
            host = parts[0]
            # \\host\share\USERFOLDER\login\scan -> share\USERFOLDER
            base_parts = parts[1:-2] if len(parts) >= 4 else parts[1:]
            return host, "\\".join(base_parts)
    return "", r"fs\USERFOLDER"


def _safe_lines(text: str, config: AppConfig) -> list[str]:
    secrets = [config.kyocera_admin_password, config.kyocera_smb_password]
    lines = []
    for line in (text or "").splitlines():
        safe = line
        for secret in secrets:
            if secret:
                safe = safe.replace(secret, "******")
        if safe.strip():
            lines.append(safe)
    return lines
