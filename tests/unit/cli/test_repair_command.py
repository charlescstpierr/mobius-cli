import json
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


def test_repair_command_json_reports_applied_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    with EventStore(home / "events.db"):
        pass
    script = project / "broken-script"
    script.write_text("#!/nonexistent/python\nprint('broken')\n", encoding="utf-8")
    monkeypatch.chdir(project)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["repair", "--json"],
        env={"MOBIUS_HOME": str(home)},
        catch_exceptions=False,
        prog_name="mobius",
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert any(item["repair_type"] == "shebang" for item in payload)


def test_repair_command_reports_no_repairs_for_clean_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    with EventStore(home / "events.db"):
        pass
    (home / "config.json").write_text(
        '{\n  "log_level": "info",\n  "profile": "dev"\n}\n',
        encoding="utf-8",
    )
    (home / "config.json").chmod(0o600)
    clean_project = tmp_path / "project"
    clean_project.mkdir()
    monkeypatch.chdir(clean_project)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["repair"],
        env={"MOBIUS_HOME": str(home)},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "no repairs needed" in result.stdout


def test_repair_command_human_output_reports_applied_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    paths = get_paths(home)
    with EventStore(paths.event_store):
        pass
    paths.config_file.unlink(missing_ok=True)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["repair"],
        env={"MOBIUS_HOME": str(home)},
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "config:" in result.stdout
    assert "missing -> default config mode 0600" in result.stdout


def test_repair_command_reports_os_errors(tmp_path: Path) -> None:
    home = tmp_path / "home"

    with mock.patch(
        "mobius.workflow.repair.run_repair",
        side_effect=NotADirectoryError("not a directory"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["repair"],
            env={"MOBIUS_HOME": str(home)},
            catch_exceptions=False,
        )

    assert result.exit_code == 1
