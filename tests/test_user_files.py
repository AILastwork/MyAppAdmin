from __future__ import annotations

from app.services.user_files import create_user_workspace


def test_create_user_workspace_from_template(tmp_path):
    template = tmp_path / "default.v8i"
    template.write_text("[Base]\nConnect=Srvr=\"srv\";Ref=\"ref\";\n", encoding="utf-8-sig")

    result = create_user_workspace(
        login="i.ivanov",
        userfolder_root=tmp_path / "USERFOLDER",
        template_path=template,
    )

    assert result.user_dir.exists()
    assert result.scan_dir.exists()
    assert result.onec_dir.exists()
    assert result.ibases_path.exists()
    assert result.start_cfg_path.exists()
    assert result.created_user_dir is True
    assert result.created_scan_dir is True


def test_create_user_workspace_supports_separate_scan_and_1c_roots(tmp_path):
    result = create_user_workspace(
        login="i.ivanov",
        userfolder_root=tmp_path / "USERFOLDER",
        scan_root=tmp_path / "SCAN",
        onec_root=tmp_path / "ONEC",
    )

    assert result.user_dir == tmp_path / "USERFOLDER" / "i.ivanov"
    assert result.scan_dir == tmp_path / "SCAN" / "i.ivanov" / "scan"
    assert result.onec_dir == tmp_path / "ONEC" / "i.ivanov"
    assert result.ibases_path == tmp_path / "ONEC" / "i.ivanov" / "ibases.v8i"
    assert result.start_cfg_path == tmp_path / "ONEC" / "i.ivanov" / "1CEStart.cfg"
    assert result.scan_dir.exists()
    assert result.ibases_path.exists()


def test_create_user_workspace_rejects_path_login(tmp_path):
    try:
        create_user_workspace("../bad", tmp_path)
    except ValueError as exc:
        assert "Login" in str(exc)
    else:
        raise AssertionError("Ожидалась ошибка валидации login")
