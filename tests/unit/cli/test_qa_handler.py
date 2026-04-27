"""Unit tests for the qa CLI command handler module."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode
from mobius.persistence.event_store import EventStore


@pytest.fixture
def qa_command() -> ModuleType:
    sys.modules.pop("mobius.cli.commands.qa", None)
    return importlib.import_module("mobius.cli.commands.qa")


def _make_context(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


def _write_run(mobius_home: Path, run_id: str, *, status: str = "completed") -> None:
    db_path = mobius_home / "events.db"
    with EventStore(db_path) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"spec_path": "/tmp/spec.yaml", "project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "g"})
        if status == "completed":
            store.append_event(
                run_id,
                "run.completed",
                {"success_criteria_count": 2, "constraint_count": 1},
            )
        else:
            store.append_event(run_id, "run.failed", {"reason": "boom"})
        store.end_session(run_id, status=status)


def test_qa_run_passes_completed_run_writes_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    context = _make_context(tmp_path)
    _write_run(context.mobius_home, "run_good", status="completed")

    qa_command.run(context, "run_good", offline=True, json_output=False)

    captured = capsys.readouterr()
    assert "# QA run_good" in captured.out
    assert "| Check | Result | Detail |" in captured.out
    assert captured.err == ""


def test_qa_run_passes_completed_run_writes_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    context = _make_context(tmp_path)
    _write_run(context.mobius_home, "run_good", status="completed")

    qa_command.run(context, "run_good", offline=True, json_output=True)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["run_id"] == "run_good"
    assert payload["mode"] == "offline"
    assert payload["summary"]["failed"] == 0


def test_qa_run_fails_for_known_bad_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    context = _make_context(tmp_path)
    _write_run(context.mobius_home, "run_bad", status="failed")

    with pytest.raises(typer.Exit) as exc:
        qa_command.run(context, "run_bad", offline=True, json_output=True)

    assert exc.value.exit_code == int(ExitCode.GENERIC_ERROR)
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["failed"] > 0


def test_qa_run_rejects_non_offline_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    context = _make_context(tmp_path)

    with pytest.raises(typer.Exit) as exc:
        qa_command.run(context, "run_x", offline=False)

    assert exc.value.exit_code == int(ExitCode.VALIDATION)
    err = capsys.readouterr().err
    assert "offline mode only" in err


def test_qa_run_returns_not_found_for_unknown_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    context = _make_context(tmp_path)
    # Pre-create an empty store so the QA command can open it.
    with EventStore(context.mobius_home / "events.db"):
        pass

    with pytest.raises(typer.Exit) as exc:
        qa_command.run(context, "run_missing", offline=True)

    assert exc.value.exit_code == int(ExitCode.NOT_FOUND)
    assert "not found" in capsys.readouterr().err.lower()


def test_qa_run_uses_context_json_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], qa_command: ModuleType
) -> None:
    """``context.json_output=True`` should switch markdown→JSON without --json."""
    context = _make_context(tmp_path, json_output=True)
    _write_run(context.mobius_home, "run_good", status="completed")

    qa_command.run(context, "run_good", offline=True, json_output=False)

    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run_good"
