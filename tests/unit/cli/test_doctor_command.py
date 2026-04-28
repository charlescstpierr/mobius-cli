import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.persistence.event_store import EventStore


def _prepare_home(home: Path) -> None:
    home.mkdir(mode=0o700)
    with EventStore(home / "events.db"):
        pass


def _run_doctor(tmp_path: Path, home: Path, *args: str) -> object:
    runner = CliRunner()
    return runner.invoke(
        app,
        ["doctor", "--json", *args],
        env={"MOBIUS_HOME": str(home)},
        catch_exceptions=False,
    )


def test_doctor_json_reports_all_checks_and_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _prepare_home(home)
    monkeypatch.chdir(project)

    result = _run_doctor(tmp_path, home)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert {item["check_name"] for item in payload} == {
        "python_env",
        "shebang_check",
        "mobius_home",
        "sqlite_health",
        "spec_valid",
        "permissions",
    }
    assert all(item["status"] in {"ok", "warn", "fail"} for item in payload)
    with EventStore(home / "events.db") as store:
        count = store.connection.execute(
            "SELECT count(*) FROM events WHERE type = 'doctor.check_completed'"
        ).fetchone()[0]
    assert count == len(payload)


def test_doctor_detects_stale_shebang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _prepare_home(home)
    script = project / "broken-script"
    script.write_text("#!/nonexistent/python\nprint('broken')\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.chdir(project)

    result = _run_doctor(tmp_path, home)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    shebang = next(item for item in payload if item["check_name"] == "shebang_check")
    assert shebang["status"] == "fail"
    assert "broken-script" in shebang["details"]
    assert "/nonexistent/python" in shebang["details"]


def test_doctor_reports_bad_mobius_home_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    _prepare_home(home)
    home.chmod(0o755)
    monkeypatch.chdir(project)

    result = _run_doctor(tmp_path, home)

    payload = json.loads(result.stdout)
    by_name = {item["check_name"]: item for item in payload}
    assert by_name["mobius_home"]["status"] != "ok" or by_name["permissions"]["status"] != "ok"
