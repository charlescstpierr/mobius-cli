"""Branch coverage for the run workflow worker, signal handlers, and stale-pid logic."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from mobius.cli.main import ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.run import (
    RunInterrupted,
    execute_run,
    get_run_paths,
    mark_stale_run_if_needed,
    prepare_run,
)
from mobius.workflow.seed import SeedSpecValidationError


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Test crash paths
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )
    return spec


def test_mark_stale_run_no_pid_file_is_noop(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    # Should not raise
    mark_stale_run_if_needed(paths, "run_x")


def test_mark_stale_run_with_dead_pid_marks_crashed(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    run_paths = get_run_paths(paths, "run_dead")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text("2999999\n", encoding="utf-8")

    mark_stale_run_if_needed(paths, "run_dead")
    assert not run_paths.pid_file.exists()
    with EventStore(paths.event_store) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            ("run_dead",),
        ).fetchone()
    assert row["status"] == "crashed"


def test_mark_stale_run_with_invalid_pid_text_marks_crashed(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    run_paths = get_run_paths(paths, "run_garbage")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text("not-a-pid\n", encoding="utf-8")

    mark_stale_run_if_needed(paths, "run_garbage")
    assert not run_paths.pid_file.exists()


def test_mark_stale_run_skips_when_pid_alive(tmp_path: Path) -> None:
    """If the PID is the current process (always alive), nothing changes."""
    import os

    paths = get_paths(tmp_path / "h")
    run_paths = get_run_paths(paths, "run_alive")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    mark_stale_run_if_needed(paths, "run_alive")
    assert run_paths.pid_file.exists()


def test_run_interrupted_sigterm_marks_cancelled(tmp_path: Path) -> None:
    """v0.1.4 contract: the worker is authoritative for ``run.cancelled``.
    A second SIGTERM must not produce a duplicate event (idempotent).
    """
    paths = get_paths(tmp_path / "h")
    run_paths = get_run_paths(paths, "run_x")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    pid_file = run_paths.pid_file
    pid_file.write_text(f"{1234567}\n", encoding="utf-8")

    with EventStore(paths.event_store) as store:
        store.create_session("run_x", runtime="run", metadata={}, status="running")

    interrupted = RunInterrupted(paths=paths, run_id="run_x", pid_file=pid_file)
    with pytest.raises(SystemExit) as exc:
        interrupted.handle_sigterm(signal.SIGTERM, None)
    assert exc.value.code == int(ExitCode.OK)

    with EventStore(paths.event_store) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            ("run_x",),
        ).fetchone()
        events = [event.type for event in store.read_events("run_x")]
    assert row["status"] == "cancelled"
    assert events.count("run.cancelled") == 1
    assert not pid_file.exists()


def test_run_interrupted_sigint_marks_interrupted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = get_paths(tmp_path / "h")
    run_paths = get_run_paths(paths, "run_y")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    pid_file = run_paths.pid_file
    pid_file.write_text(f"{1234568}\n", encoding="utf-8")

    with EventStore(paths.event_store) as store:
        store.create_session("run_y", runtime="run", metadata={}, status="running")

    interrupted = RunInterrupted(paths=paths, run_id="run_y", pid_file=pid_file)
    with pytest.raises(SystemExit) as exc:
        interrupted.handle_sigint(signal.SIGINT, None)
    assert exc.value.code == int(ExitCode.INTERRUPTED)
    assert "interrupted" in capsys.readouterr().err

    with EventStore(paths.event_store) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            ("run_y",),
        ).fetchone()
    assert row["status"] == "interrupted"


def test_execute_run_missing_metadata_raises_validation(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    # Provide a bare directory but no metadata file.
    run_paths = get_run_paths(paths, "run_no_meta")
    run_paths.directory.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SeedSpecValidationError, match="run metadata"):
        execute_run(paths, "run_no_meta", stream_events=False)


def test_execute_run_invalid_metadata_raises_validation(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    run_paths = get_run_paths(paths, "run_bad_meta")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.metadata_file.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(SeedSpecValidationError, match="missing spec_path"):
        execute_run(paths, "run_bad_meta", stream_events=False)


def test_execute_run_spec_validation_failure_returns_validation(
    tmp_path: Path,
) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text("project_type: greenfield\n", encoding="utf-8")

    run_paths = get_run_paths(paths, "run_bad_spec")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.metadata_file.write_text(
        json.dumps({"spec_path": str(bad_spec)}),
        encoding="utf-8",
    )

    code = execute_run(paths, "run_bad_spec", stream_events=False)
    assert code == int(ExitCode.VALIDATION)


def test_prepare_run_propagates_seed_validation_error(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    bad = tmp_path / "bad.yaml"
    bad.write_text("project_type: marsfield\n", encoding="utf-8")

    with pytest.raises(SeedSpecValidationError):
        prepare_run(paths, bad)
