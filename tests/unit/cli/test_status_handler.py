"""Direct unit tests for the status command handler."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


@pytest.fixture
def status_command() -> ModuleType:
    sys.modules.pop("mobius.cli.commands.status", None)
    return importlib.import_module("mobius.cli.commands.status")


def _ctx(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


def test_status_handler_store_status_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    status_command.run(_ctx(tmp_path), None)
    out = capsys.readouterr().out
    assert "event_store=" in out
    assert "integrity_check=ok" in out


def test_status_handler_store_status_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    status_command.run(_ctx(tmp_path), None, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrity_check"] == "ok"


def test_status_handler_run_id_unknown_exits_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store):
        pass
    with pytest.raises(SystemExit) as exc:
        status_command.run(_ctx(tmp_path), "run_missing")
    assert exc.value.code == int(ExitCode.NOT_FOUND)


def test_status_handler_known_run_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_x", runtime="run", metadata={}, status="completed")
    status_command.run(_ctx(tmp_path), "run_x")
    out = capsys.readouterr().out
    assert "# Run run_x" in out
    assert "completed" in out


def test_status_handler_resolves_unique_run_slug_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("abc-def-123", runtime="run", metadata={}, status="completed")
        store.append_event("abc-def-123", "run.started", {"goal": "Prefix"})

    status_command.run(_ctx(tmp_path), "abc-def")
    out = capsys.readouterr().out
    assert "# Run abc-def-123" in out


def test_status_handler_rejects_ambiguous_run_slug_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        for run_id in ("abc-def-123", "abc-different-456"):
            store.create_session(run_id, runtime="run", metadata={}, status="completed")
            store.append_event(run_id, "run.started", {"goal": run_id})

    with pytest.raises(SystemExit) as exc:
        status_command.run(_ctx(tmp_path), "abc-")

    assert exc.value.code == int(ExitCode.USAGE)
    err = capsys.readouterr().err
    assert "ambiguous run prefix" in err
    assert "abc-def-123" in err
    assert "abc-different-456" in err


def test_status_handler_follow_requires_run_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status_command: ModuleType
) -> None:
    with pytest.raises(SystemExit) as exc:
        status_command.run(_ctx(tmp_path), None, follow=True)
    assert exc.value.code == int(ExitCode.USAGE)


def test_mark_stale_session_runtime_from_run_pid_file(
    tmp_path: Path, status_command: ModuleType
) -> None:
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    # Pre-create the runs directory and a stale PID file but no DB session yet.
    from mobius.workflow.run import get_run_paths

    run_paths = get_run_paths(paths, "run_orphan")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text("2999998\n", encoding="utf-8")

    status_command.mark_stale_session_if_needed(paths, "run_orphan")
    assert not run_paths.pid_file.exists()


def test_mark_stale_session_runtime_from_evolution_pid_file(
    tmp_path: Path, status_command: ModuleType
) -> None:
    from mobius.workflow.evolve import get_evolution_paths

    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    evo_paths = get_evolution_paths(paths, "evo_orphan")
    evo_paths.directory.mkdir(parents=True, exist_ok=True)
    evo_paths.pid_file.write_text("2999997\n", encoding="utf-8")

    status_command.mark_stale_session_if_needed(paths, "evo_orphan")
    assert not evo_paths.pid_file.exists()


def test_mark_stale_session_terminal_session_just_cleans_pid(
    tmp_path: Path, status_command: ModuleType
) -> None:
    from mobius.workflow.run import get_run_paths

    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_done", runtime="run", metadata={}, status="completed")
    run_paths = get_run_paths(paths, "run_done")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text("2999996\n", encoding="utf-8")

    status_command.mark_stale_session_if_needed(paths, "run_done")
    assert not run_paths.pid_file.exists()


def test_mark_stale_session_alive_pid_is_noop(tmp_path: Path, status_command: ModuleType) -> None:
    from mobius.workflow.run import get_run_paths

    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_alive", runtime="run", metadata={}, status="running")
    run_paths = get_run_paths(paths, "run_alive")
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    status_command.mark_stale_session_if_needed(paths, "run_alive")
    assert run_paths.pid_file.exists()


def test_status_handler_follow_streams_until_terminal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status_command: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive --follow through one iteration with mocked time.sleep."""
    paths = get_paths(_ctx(tmp_path).mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_follow", runtime="run", metadata={}, status="completed")
        store.append_event("run_follow", "run.completed", {"ok": True})

    # No-op sleep so we don't actually wait.
    monkeypatch.setattr(status_command.time, "sleep", lambda _seconds: None)

    status_command.run(_ctx(tmp_path), "run_follow", follow=True)
    out = capsys.readouterr().out
    assert "# Run run_follow" in out
