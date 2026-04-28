import json
from pathlib import Path

from typer.testing import CliRunner

from mobius.cli.main import app


def test_migrate_command_json_reports_changed_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        """goal: Ship
constraints:
  - c
success_criteria:
  - s
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["migrate", str(spec_path), "--json"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["changed"] is True
    assert payload["backup_created"] is True
    assert spec_path.read_text(encoding="utf-8").startswith("spec_version: 2\n")
    assert (tmp_path / "spec.yaml.v1.bak").exists()


def test_migrate_command_reports_noop_for_v2_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        """spec_version: 2
goal: Ship
constraints:
  - c
success_criteria:
  - s
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["migrate", str(spec_path)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "already spec_version: 2" in result.stdout
    assert not (tmp_path / "spec.yaml.v1.bak").exists()


def test_migrate_command_reports_missing_spec(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["migrate", str(tmp_path / "missing.yaml")],
        catch_exceptions=False,
    )

    assert result.exit_code == 4
    assert "spec file not found" in result.stderr
