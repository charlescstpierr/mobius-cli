import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from mobius.persistence.event_store import EventStore
from mobius.workflow import doctor as doctor_module


def test_python_env_reports_missing_and_non_executable_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "missing-python"))
    missing = doctor_module._check_python_env()
    assert missing.status == "fail"
    assert "does not exist" in missing.details

    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o644)
    monkeypatch.setattr(sys, "executable", str(python))
    not_executable = doctor_module._check_python_env()
    assert not_executable.status == "fail"
    assert "not executable" in not_executable.details


def test_python_env_reports_uv_oserror_timeout_and_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))

    with mock.patch("subprocess.run", side_effect=OSError("no uv")):
        os_error = doctor_module._check_python_env()
    assert os_error.status == "fail"
    assert "uv is not runnable" in os_error.details

    import subprocess

    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 5)):
        timeout = doctor_module._check_python_env()
    assert timeout.status == "fail"
    assert "uv is not runnable" in timeout.details

    completed = subprocess.CompletedProcess(["uv"], 2, stdout="", stderr="bad uv")
    with mock.patch("subprocess.run", return_value=completed):
        nonzero = doctor_module._check_python_env()
    assert nonzero.status == "fail"
    assert "exited 2" in nonzero.details


def test_shebang_scanner_reports_missing_targets_and_limits_details(tmp_path: Path) -> None:
    for index in range(6):
        script = tmp_path / f"script-{index}"
        script.write_text(f"#!/missing/python-{index}\necho nope\n", encoding="utf-8")
        script.chmod(0o755)
    (tmp_path / "node_modules").mkdir()
    skipped = tmp_path / "node_modules" / "ignored"
    skipped.write_text("#!/also/missing\n", encoding="utf-8")

    check = doctor_module._check_shebangs(tmp_path)

    assert check.status == "fail"
    assert "script-0" in check.details
    assert "(+1 more)" in check.details
    assert "ignored" not in check.details


def test_shebang_scanner_detects_project_venv_script_pointing_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_python = tmp_path / "current" / "bin" / "python"
    current_python.parent.mkdir(parents=True)
    current_python.write_text("#!/bin/sh\n", encoding="utf-8")
    current_python.chmod(0o755)
    other_python = tmp_path / "other" / "bin" / "python"
    other_python.parent.mkdir(parents=True)
    other_python.write_text("#!/bin/sh\n", encoding="utf-8")
    other_python.chmod(0o755)
    script = tmp_path / ".venv" / "bin" / "pytest"
    script.parent.mkdir(parents=True)
    script.write_text(f"#!{other_python}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(current_python))

    stale = doctor_module._find_stale_shebangs(tmp_path)

    assert stale == [(".venv/bin/pytest", str(other_python))]


def test_mobius_home_statuses_and_permission_format(tmp_path: Path) -> None:
    missing = doctor_module._check_mobius_home(tmp_path / "missing")
    assert missing.status == "fail"
    file_home = tmp_path / "file-home"
    file_home.write_text("not a dir", encoding="utf-8")
    assert doctor_module._check_mobius_home(file_home).status == "fail"

    warn_home = tmp_path / "warn-home"
    warn_home.mkdir()
    warn_home.chmod(0o755)
    warn = doctor_module._check_mobius_home(warn_home)
    assert warn.status == "warn"
    assert "0755" in warn.details

    ok_home = tmp_path / "ok-home"
    ok_home.mkdir(mode=0o700)
    ok_home.chmod(0o700)
    assert doctor_module._check_mobius_home(ok_home).status == "ok"


def test_sqlite_health_handles_missing_invalid_and_incomplete_db(tmp_path: Path) -> None:
    missing = doctor_module._check_sqlite_health(tmp_path / "missing.db")
    assert missing.status == "warn"

    invalid = tmp_path / "invalid.db"
    invalid.write_text("not sqlite", encoding="utf-8")
    assert doctor_module._check_sqlite_health(invalid).status == "fail"

    incomplete = tmp_path / "incomplete.db"
    connection = sqlite3.connect(incomplete)
    connection.execute("CREATE TABLE events(event_id TEXT)")
    connection.commit()
    connection.close()
    incomplete_check = doctor_module._check_sqlite_health(incomplete)
    assert incomplete_check.status == "fail"
    assert "missing tables" in incomplete_check.details

    healthy = tmp_path / "healthy.db"
    with EventStore(healthy):
        pass
    assert doctor_module._check_sqlite_health(healthy).status == "ok"


def test_sqlite_health_handles_query_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "healthy.db"
    with EventStore(db_path):
        pass

    class BadConnection:
        def execute(self, _sql: str) -> object:
            raise sqlite3.OperationalError("boom")

        def close(self) -> None:
            pass

    with mock.patch.object(sqlite3, "connect", return_value=BadConnection()):
        check = doctor_module._check_sqlite_health(db_path)
    assert check.status == "fail"
    assert "sqlite health check failed" in check.details


def test_spec_check_reports_absent_invalid_and_valid_specs(tmp_path: Path) -> None:
    assert doctor_module._check_spec(tmp_path).status == "ok"

    bad_project = tmp_path / "bad"
    bad_project.mkdir()
    (bad_project / "spec.yaml").write_text("project_type: nope\n", encoding="utf-8")
    bad = doctor_module._check_spec(bad_project)
    assert bad.status == "fail"
    assert "invalid" in bad.details

    good_project = tmp_path / "good"
    good_project.mkdir()
    (good_project / "spec.yaml").write_text(
        "goal: Ship\nconstraints:\n  - one\nsuccess_criteria:\n  - done\n",
        encoding="utf-8",
    )
    assert doctor_module._check_spec(good_project).status == "ok"


def test_permission_check_statuses(tmp_path: Path) -> None:
    missing = doctor_module._check_permissions(tmp_path / "missing.db")
    assert missing.status == "warn"

    db_path = tmp_path / "events.db"
    with EventStore(db_path):
        pass
    db_path.chmod(0o644)
    warn = doctor_module._check_permissions(db_path)
    assert warn.status == "warn"
    assert "0644" in warn.details

    db_path.chmod(0o600)
    assert doctor_module._check_permissions(db_path).status == "ok"


def test_emit_check_events_swallows_store_errors(tmp_path: Path) -> None:
    check = doctor_module.DoctorCheck("x", "ok", "fine")
    with mock.patch.object(doctor_module, "EventStore", side_effect=RuntimeError("boom")):
        doctor_module._emit_check_events(tmp_path / "events.db", [check])


def test_run_doctor_emits_all_checks_for_healthy_temp_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    project = tmp_path / "project"
    project.mkdir()
    with EventStore(home / "events.db"):
        pass

    import subprocess

    completed = subprocess.CompletedProcess(["uv"], 0, stdout="uv 1.0\n", stderr="")
    with mock.patch("subprocess.run", return_value=completed):
        checks = doctor_module.run_doctor(cwd=project, mobius_home=home)

    assert [check.check_name for check in checks] == [
        "python_env",
        "shebang_check",
        "mobius_home",
        "sqlite_health",
        "spec_valid",
        "permissions",
    ]
    with EventStore(home / "events.db") as store:
        count = store.connection.execute(
            "SELECT count(*) FROM events WHERE type = 'doctor.check_completed'"
        ).fetchone()[0]
    assert count == 6

