import json
from pathlib import Path

import click
import pytest

from mobius.cli.commands import config as config_command
from mobius.cli.commands import seed as seed_command
from mobius.cli.commands import status as status_command
from mobius.cli.main import CliContext
from mobius.persistence.event_store import EventStore


@pytest.fixture
def context(tmp_path: Path) -> CliContext:
    return CliContext(json_output=False, mobius_home=tmp_path / "home")


@pytest.fixture
def captured_output(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {"stdout": [], "json": [], "stderr": []}
    monkeypatch.setattr(
        "mobius.cli.output.write_line",
        lambda message: captured["stdout"].append(message),
    )
    monkeypatch.setattr(
        "mobius.cli.output.write_json",
        lambda message: captured["json"].append(message),
    )
    monkeypatch.setattr(
        "mobius.cli.output.write_error_line",
        lambda message: captured["stderr"].append(message),
    )
    return captured


def write_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Exercise seed command handler directly.
constraints:
  - Persist validated seed events
success_criteria:
  - Handler emits structured output
""".strip(),
        encoding="utf-8",
    )


def test_config_handlers_emit_json_and_text_without_subprocess(
    context: CliContext,
    captured_output: dict[str, list[str]],
) -> None:
    config_command.set_value(context, "profile", "prod", json_output=True)
    config_command.get(context, "profile")
    config_command.show(context, json_output=True)

    set_payload = json.loads(captured_output["json"][0])
    show_payload = json.loads(captured_output["json"][1])

    assert set_payload == {"key": "profile", "value": "prod"}
    assert captured_output["stdout"] == ["prod"]
    assert show_payload["state_dir"] == str(context.mobius_home)
    assert show_payload["busy_timeout"] == 30_000
    assert show_payload["values"]["profile"] == "prod"
    assert captured_output["stderr"] == []


def test_config_get_unknown_key_uses_not_found_exit_code(
    context: CliContext,
    captured_output: dict[str, list[str]],
) -> None:
    with pytest.raises(click.exceptions.Exit) as exc_info:
        config_command.get(context, "does_not_exist")

    assert exc_info.value.exit_code == 4
    assert captured_output["stdout"] == []
    assert captured_output["stderr"] == ["config key not found: does_not_exist"]


def test_seed_handler_persists_three_events_and_completed_session(
    tmp_path: Path,
    context: CliContext,
    captured_output: dict[str, list[str]],
) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)

    seed_command.run(context, str(spec), json_output=True)

    payload = json.loads(captured_output["json"][0])
    session_id = payload["session_id"]
    assert session_id.startswith("seed_exercise-seed-command-handler_")
    assert payload["event_count"] == 3
    with EventStore(context.mobius_home / "events.db") as store:
        events = store.read_events(session_id)
        session = store.connection.execute(
            "SELECT status, runtime FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    assert [event.type for event in events] == [
        "seed.started",
        "seed.validated",
        "seed.completed",
    ]
    assert session["status"] == "completed"
    assert session["runtime"] == "seed"


def test_status_handler_reports_store_health_and_run_not_found_exit(
    context: CliContext,
    captured_output: dict[str, list[str]],
) -> None:
    status_command.run(context, json_output=True)
    health = json.loads(captured_output["json"][0])

    assert health["integrity_check"] == "ok"
    assert health["migrations_applied"] is True
    assert health["event_count"] >= 1

    with pytest.raises(SystemExit) as exc_info:
        status_command.run(context, "run_missing")

    assert exc_info.value.code == 4
    assert captured_output["stderr"] == ["run not found: run_missing"]
