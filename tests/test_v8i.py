from __future__ import annotations

import pytest

from app.services.v8i import (
    V8iBase,
    build_1cestart_cfg,
    normalize_ibases_path,
    parse_v8i,
    rename_template_profile,
    write_v8i,
)


def test_parse_and_write_v8i_roundtrip(tmp_path):
    path = tmp_path / "ibases.v8i"
    bases = [
        V8iBase("Бухгалтерия ПРОФ", {"Connect": 'Srvr="1C-SRV01";Ref="Accounting";', "ClientConnectionSpeed": "Normal"}),
        V8iBase("ЗУП", {"Connect": 'Srvr="1C-SRV01";Ref="ZUP";'}),
    ]

    write_v8i(bases, path)
    parsed = parse_v8i(path)

    assert [item.name for item in parsed] == ["Бухгалтерия ПРОФ", "ЗУП"]
    assert parsed[0].server() == "1C-SRV01"
    assert parsed[0].ref() == "Accounting"


def test_build_1cestart_cfg_contains_common_path():
    cfg = build_1cestart_cfg(r"\\server\share\user\ibases.v8i")

    assert "[COMMON]" in cfg
    assert "UseHWLicenses=0" in cfg
    assert r"CommonInfoBases=\\server\share\user\ibases.v8i" in cfg


def test_normalize_ibases_path_appends_filename_for_directory_like_path():
    assert str(normalize_ibases_path(r"\\localhost\test\\")) == r"\\localhost\test\ibases.v8i"
    assert str(normalize_ibases_path(r"\\localhost\test")) == r"\\localhost\test\ibases.v8i"


def test_rename_template_profile_moves_file_and_adds_extension(tmp_path):
    source = tmp_path / "old.v8i"
    source.write_text("[Base]\n", encoding="utf-8")

    target = rename_template_profile(source, "new")

    assert target == tmp_path / "new.v8i"
    assert target.read_text(encoding="utf-8") == "[Base]\n"
    assert not source.exists()


def test_rename_template_profile_does_not_overwrite_existing_file(tmp_path):
    source = tmp_path / "old.v8i"
    target = tmp_path / "new.v8i"
    source.write_text("old", encoding="utf-8")
    target.write_text("new", encoding="utf-8")

    with pytest.raises(FileExistsError):
        rename_template_profile(source, target.name)

    assert source.read_text(encoding="utf-8") == "old"
    assert target.read_text(encoding="utf-8") == "new"
