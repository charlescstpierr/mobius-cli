from __future__ import annotations

import json
from pathlib import Path

import pytest

from mobius.persistence.event_store import EventRecord, iso8601_utc_now
from mobius.workflow import doctor as doctor_module
from mobius.workflow import qa as qa_module
from mobius.workflow import verify as verify_module


def _event(event_type: str, payload: object) -> EventRecord:
    return EventRecord(
        event_id="evt",
        aggregate_id="run",
        sequence=1,
        type=event_type,
        payload=json.dumps(payload),
        created_at=iso8601_utc_now(),
    )


def test_qa_json_and_config_residual_branches(tmp_path: Path) -> None:
    assert qa_module._decode_json_object("{not json") == {}
    assert qa_module._decode_json_object("[1, 2]") == {}
    assert qa_module._load_success_criteria_count([_event("run.started", {})]) == 0
    assert qa_module._load_success_criteria_count(
        [_event("run.completed", {"success_criteria_count": "many"})]
    ) == 0
    assert qa_module._load_success_criteria_count(
        [_event("run.completed", {"success_criteria_count": 3})]
    ) == 3

    config = tmp_path / "config.json"
    config.write_text("{not json", encoding="utf-8")
    assert qa_module._load_verification_config(tmp_path) == {}
    config.write_text("[1, 2]", encoding="utf-8")
    assert qa_module._load_verification_config(tmp_path) == {}
    config.write_text('{"timeout_s": 5}', encoding="utf-8")
    assert qa_module._load_verification_config(tmp_path) == {"timeout_s": 5}
    assert qa_module._owner_present(["", "owner"]) is True
    assert qa_module._owner_present(["", " "]) is False


def test_verify_validation_and_output_cap_residual_branches() -> None:
    assert verify_module._criterion_ref({"criterion_refs": []}) == "[]"
    assert verify_module._coerce_output(None) == ""
    assert verify_module._coerce_output(b"caf\xc3\xa9") == "café"
    assert verify_module._cap_outputs("ok", "", 10) == ("ok", "", False)
    assert verify_module._cap_outputs("", "abcdef", 4)[1]

    with pytest.raises(ValueError, match="max_output_bytes"):
        verify_module._max_output_bytes({"max_output_bytes": "NaN"})
    with pytest.raises(ValueError, match="greater than zero"):
        verify_module._max_output_bytes({"max_output_bytes": 0})


def test_doctor_home_sqlite_and_shebang_residual_branches(tmp_path: Path) -> None:
    missing = doctor_module._check_mobius_home(tmp_path / "missing")
    assert missing.status == "fail"

    not_dir = tmp_path / "not-dir"
    not_dir.write_text("x", encoding="utf-8")
    assert doctor_module._check_mobius_home(not_dir).status == "fail"

    home = tmp_path / "home"
    home.mkdir(mode=0o755)
    home_check = doctor_module._check_mobius_home(home)
    assert home_check.status in {"warn", "ok"}

    sqlite_missing = doctor_module._check_sqlite_health(tmp_path / "missing.db")
    assert sqlite_missing.status == "warn"

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite", encoding="utf-8")
    assert doctor_module._check_sqlite_health(corrupt).status == "fail"

    script = tmp_path / "script"
    script.write_text("#!/definitely/missing/python\nprint('x')\n", encoding="utf-8")
    stale = doctor_module._find_stale_shebangs(tmp_path)
    assert stale == [("script", "/definitely/missing/python")]
