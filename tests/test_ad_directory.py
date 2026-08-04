from __future__ import annotations

from app.services.ad_directory import build_login_candidates, format_ad_datetime, format_ad_filetime, generate_password, parse_full_name


def test_parse_full_name_splits_last_first_middle():
    assert parse_full_name("Никишин Андрей Олегович") == ("Никишин", "Андрей", "Олегович")


def test_build_login_candidates_prefers_first_initial_last_then_middle_initial():
    candidates = build_login_candidates("Никишин", "Андрей", "Олегович")

    assert candidates[0] == "a.nikishin"
    assert candidates[1] == "a.o.nikishin"


def test_generate_password_has_required_character_classes():
    password = generate_password(10)

    assert len(password) == 10
    assert any(char.islower() for char in password)
    assert any(char.isupper() for char in password)
    assert any(char.isdigit() for char in password)
    assert any(char in "!@_" for char in password)


def test_format_ad_datetime_handles_generalized_time():
    assert format_ad_datetime("20260608100000.0Z").startswith("08.06.2026 ")


def test_format_ad_filetime_handles_last_logon_timestamp():
    assert "01.01.2020" in format_ad_filetime(132223104000000000)


def test_format_ad_filetime_handles_empty_values():
    assert format_ad_filetime("") == "нет данных"
