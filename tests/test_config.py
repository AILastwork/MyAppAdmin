from __future__ import annotations

import json
import os

import pytest

from app.config import (
    AppConfig,
    DEFAULT_GLPI_BASE_URL,
    DEFAULT_PRINTER_CONFIG_FILE,
    DEFAULT_SCAN_ACCOUNT,
    DEFAULT_SHARED_ROOT,
    DEFAULT_USER_1C_ROOT,
    DEFAULT_YANDEX_TOKEN_FILE,
)


def test_config_load_creates_default_file(tmp_path):
    path = tmp_path / "config.json"

    config = AppConfig.load(path)

    assert path.exists()
    assert config.domain == "OSNOVA"
    assert config.template_dir == DEFAULT_SHARED_ROOT
    assert config.yandex_token_file == DEFAULT_YANDEX_TOKEN_FILE
    assert config.printer_config_file == DEFAULT_PRINTER_CONFIG_FILE
    assert config.glpi_base_url == DEFAULT_GLPI_BASE_URL


def test_config_ignores_removed_allowlist_fields():
    data = AppConfig._normalize_data(
        {
            "allowed_login_groups": ["OSNOVA\\HelpDesk"],
            "allowed_ous": ["OU=Users,DC=example,DC=local"],
            "allowed_groups": ["VPN Users"],
            "require_allowed_login_group": True,
            "denied_groups": ["Domain Admins"],
        }
    )

    assert "allowed_login_groups" not in data
    assert "allowed_ous" not in data
    assert "allowed_groups" not in data
    assert "require_allowed_login_group" not in data
    assert "denied_groups" not in data


def test_config_migrates_legacy_workspace_defaults():
    data = AppConfig._normalize_data(
        {
            "userfolder_root": r"\\osnova.local\fs\USERFOLDER",
            "user_1c_root": r"\\osnova.local\fs\USERFOLDER",
            "scan_account": "scan_user",
        }
    )

    assert data["user_1c_root"] == DEFAULT_USER_1C_ROOT
    assert data["scan_account"] == DEFAULT_SCAN_ACCOUNT


def test_config_migrates_legacy_shared_paths():
    data = AppConfig._normalize_data(
        {
            "template_dir": r"\\osnova.local\fs\ADM_SECURE\templates_1c",
            "yandex_token_file": r"\\osnova.local\fs\ADM_SECURE\yandex_api_tokens.txt",
            "printer_config_file": r"\\osnova.local\fs\ADM_SECURE\printers.json",
        }
    )

    assert data["template_dir"] == DEFAULT_SHARED_ROOT
    assert data["yandex_token_file"] == DEFAULT_YANDEX_TOKEN_FILE
    assert data["printer_config_file"] == DEFAULT_PRINTER_CONFIG_FILE


@pytest.mark.skipif(os.name != "nt", reason="DPAPI secret storage is Windows-only")
def test_config_save_encrypts_secret_fields_with_dpapi(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(
        ad_read_password="Secret123!",
        kyocera_admin_password="AdminSecret!",
        kyocera_smb_password="SmbSecret!",
    )

    config.save(path)

    text = path.read_text(encoding="utf-8")
    assert "Secret123!" not in text
    assert "AdminSecret!" not in text
    assert "SmbSecret!" not in text
    data = json.loads(text)
    assert data["ad_read_password"].startswith("dpapi:v1:")
    assert data["kyocera_admin_password"].startswith("dpapi:v1:")
    assert data["kyocera_smb_password"].startswith("dpapi:v1:")

    loaded = AppConfig.load(path)
    assert loaded.ad_read_password == "Secret123!"
    assert loaded.kyocera_admin_password == "AdminSecret!"
    assert loaded.kyocera_smb_password == "SmbSecret!"


def test_config_load_supports_legacy_plain_secret_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"ad_read_password": "legacy-secret"}), encoding="utf-8")

    loaded = AppConfig.load(path)

    assert loaded.ad_read_password == "legacy-secret"
    text = path.read_text(encoding="utf-8")
    if os.name == "nt":
        assert "legacy-secret" not in text
        assert json.loads(text)["ad_read_password"].startswith("dpapi:v1:")
    else:
        assert "legacy-secret" in text
