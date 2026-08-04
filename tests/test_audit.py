from __future__ import annotations

from app.audit import AuditLogger, sanitize_params


def test_sanitize_params_masks_secret_values():
    safe = sanitize_params({"login": "admin", "password": "secret", "nested": {"token": "abc"}})

    assert safe["login"] == "admin"
    assert safe["password"] == "***"
    assert safe["nested"]["token"] == "***"


def test_audit_logger_writes_records(tmp_path):
    db = tmp_path / "audit.db"
    audit = AuditLogger(db)

    audit.log("test_action", object_type="test", object_name="object", params={"password": "hidden"})
    records = audit.recent()

    assert len(records) == 1
    assert records[0].action == "test_action"
    assert '"password": "***"' in records[0].params_json

