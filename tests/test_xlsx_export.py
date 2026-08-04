from __future__ import annotations

from zipfile import ZipFile

from app.services.xlsx_export import export_yandex_users_xlsx
from app.services.yandex360 import YandexOrg, YandexUser


def test_yandex_users_export_creates_valid_xlsx_package(tmp_path):
    path = tmp_path / "users.xlsx"
    org = YandexOrg(
        key="mkd-osnova.ru",
        name="OSNOVA",
        domain="mkd-osnova.ru",
        org_id="42",
        department_id="1",
        has_token=True,
    )
    users = [
        YandexUser(
            id="100",
            nickname="e.morozova",
            email="e.morozova@mkd-osnova.ru",
            display_name="Морозова Екатерина Андреевна",
            first_name="Екатерина",
            last_name="Морозова",
            middle_name="Андреевна",
            position="Бухгалтер",
            is_admin=False,
            is_enabled=True,
            created_at="2026-06-15T10:20:00Z",
        )
    ]

    saved = export_yandex_users_xlsx(path, users, org)

    assert saved == path
    assert path.exists()
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "xl/workbook.xml" in names
        assert "xl/styles.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "Морозова Екатерина Андреевна" in sheet
        assert "e.morozova@mkd-osnova.ru" in sheet
        assert '<autoFilter ref="A1:M2"/>' in sheet
        assert 'state="frozen"' in sheet
