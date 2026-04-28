import json
from unittest import mock

from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.workflow.smoke import SmokeReport, SmokeStep


def _report(*, passed: bool) -> SmokeReport:
    return SmokeReport(
        passed=passed,
        duration_ms=123,
        workspace="/tmp/mobius-smoke-test",
        mobius_home="/tmp/mobius-smoke-test/.mobius",
        run_id="run_smoke",
        steps=[
            SmokeStep(
                name="init",
                command=["mobius", "init"],
                passed=passed,
                duration_ms=10,
                exit_code=0 if passed else 1,
                detail="ok" if passed else "bad | detail",
            )
        ],
    )


def test_workflow_smoke_command_json_output() -> None:
    with mock.patch("mobius.cli.commands.smoke.run_smoke", return_value=_report(passed=True)):
        result = CliRunner().invoke(
            app,
            ["workflow", "smoke", "--json"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["steps"][0]["name"] == "init"


def test_workflow_smoke_command_human_output() -> None:
    with mock.patch("mobius.cli.commands.smoke.run_smoke", return_value=_report(passed=True)):
        result = CliRunner().invoke(
            app,
            ["workflow", "smoke"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "# Workflow smoke: PASS" in result.stdout
    assert "| init | pass | 10ms | ok |" in result.stdout


def test_workflow_smoke_command_exits_one_on_failure() -> None:
    with mock.patch("mobius.cli.commands.smoke.run_smoke", return_value=_report(passed=False)):
        result = CliRunner().invoke(
            app,
            ["workflow", "smoke"],
            catch_exceptions=False,
        )

    assert result.exit_code == 1
    assert "# Workflow smoke: FAIL" in result.stdout
    assert "bad \\| detail" in result.stdout
