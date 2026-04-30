from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode
from mobius.persistence.event_store import EventStore


@pytest.fixture
def handoff_command(reloaded_command) -> ModuleType:
    return reloaded_command("mobius.cli.commands.handoff")


def _context(tmp_path: Path) -> CliContext:
    return CliContext(json_output=False, mobius_home=tmp_path / "home")


HANDOFF_COMMAND_SPEC = """
project_type: greenfield
goal: Exercise the CLI handoff surface.
constraints:
  - Keep the CLI deterministic.
success_criteria:
  - C1
verification_commands:
  - command: "python -c 'print(1)'"
    criterion_ref: C1
risks:
  - description: CLI output could omit a marker.
owner: qa-team
non_goals:
  - Do not write prompt files.
""".strip()


def test_handoff_command_writes_prompt_and_event(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    handoff_command: ModuleType,
    spec_factory,
) -> None:
    context = _context(tmp_path)
    spec_path = spec_factory(tmp_path / "spec.yaml", body=HANDOFF_COMMAND_SPEC)

    handoff_command.run(context, agent="hermes", spec_path=spec_path, dry_run=True)

    captured = capsys.readouterr()
    assert "<GOAL>" in captured.out
    assert "<CRITERIA>" in captured.out
    assert "<COMMANDS>" in captured.out
    assert "<RISKS>" in captured.out
    assert "Exercise the CLI handoff surface." in captured.out
    with EventStore(context.mobius_home / "events.db", read_only=True) as store:
        events = store.read_events(f"handoff:{spec_path.resolve()}")
    payloads = [event.payload_data for event in events if event.type == "handoff.generated"]
    assert payloads == [
        {
            "agent": "hermes",
            "criteria_count": 1,
            "dry_run": True,
            "template_version": 1,
        }
    ]


def test_handoff_command_rejects_unknown_agent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    handoff_command: ModuleType,
    spec_factory,
) -> None:
    spec_path = spec_factory(tmp_path / "spec.yaml", body=HANDOFF_COMMAND_SPEC)

    with pytest.raises(typer.Exit) as exc:
        handoff_command.run(_context(tmp_path), agent="unknown", spec_path=spec_path, dry_run=True)

    assert exc.value.exit_code == int(ExitCode.USAGE)
    assert "unknown handoff agent" in capsys.readouterr().err


def test_handoff_event_payload_is_json_serializable(
    tmp_path: Path, handoff_command: ModuleType, spec_factory
) -> None:
    spec_path = spec_factory(tmp_path / "spec.yaml", body=HANDOFF_COMMAND_SPEC)
    context = _context(tmp_path)

    handoff_command.run(
        context,
        agent="claude",
        spec_path=spec_path,
        dry_run=False,
    )

    with EventStore(context.mobius_home / "events.db", read_only=True) as store:
        event = next(
            event
            for event in store.read_events(f"handoff:{spec_path.resolve()}")
            if event.type == "handoff.generated"
        )
    assert json.loads(event.payload)["template_version"] == 1
