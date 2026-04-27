import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.cancel import CancelResult, cancel_run
from mobius.workflow.run import get_run_paths


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_dead(pid: int) -> None:
    deadline = time.monotonic() + 5
    while _pid_is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _pid_is_live(pid)


def _start_sigterm_ignoring_process() -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import signal,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "print('ready', flush=True);"
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    return process


def test_cancel_unknown_run_returns_not_found(tmp_path: Path) -> None:
    result = cancel_run(get_paths(tmp_path / "home"), "run_missing", grace_period=0.01)

    assert result is CancelResult.NOT_FOUND


def test_cancel_already_finished_run_is_noop(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "home")
    with EventStore(paths.event_store) as store:
        store.create_session("run_done", runtime="run", status="running")
        store.end_session("run_done", status="completed")

    result = cancel_run(paths, "run_done", grace_period=0.01)

    assert result is CancelResult.ALREADY_FINISHED


def test_cancel_unknown_run_does_not_read_or_signal_fabricated_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = get_paths(tmp_path / "home")
    run_paths = get_run_paths(paths, "run_missing")
    run_paths.directory.mkdir(parents=True)
    run_paths.pid_file.write_text("12345\n", encoding="utf-8")

    def fail_if_pid_read(_pid_file: os.PathLike[str]) -> int:
        raise AssertionError("unknown sessions must be rejected before reading PID files")

    def fail_if_signal_sent(_pid: int, *, grace_period: float) -> bool:
        raise AssertionError("unknown sessions must not signal fabricated PIDs")

    monkeypatch.setattr("mobius.workflow.cancel._read_pid", fail_if_pid_read)
    monkeypatch.setattr("mobius.workflow.cancel._terminate_process", fail_if_signal_sent)

    result = cancel_run(paths, "run_missing", grace_period=0.01)

    assert result is CancelResult.NOT_FOUND
    assert run_paths.pid_file.exists()
    with EventStore(paths.event_store) as store:
        session = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            ("run_missing",),
        ).fetchone()
    assert session is None


def test_cancel_terminal_run_removes_stale_pid_without_reading_or_signaling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = get_paths(tmp_path / "home")
    run_id = "run_done"
    with EventStore(paths.event_store) as store:
        store.create_session(run_id, runtime="run", status="running")
        store.end_session(run_id, status="completed")
    run_paths = get_run_paths(paths, run_id)
    run_paths.directory.mkdir(parents=True)
    run_paths.pid_file.write_text("12345\n", encoding="utf-8")

    def fail_if_pid_read(_pid_file: os.PathLike[str]) -> int:
        raise AssertionError("terminal sessions must be handled before reading PID files")

    def fail_if_signal_sent(_pid: int, *, grace_period: float) -> bool:
        raise AssertionError("terminal sessions must not signal stale PIDs")

    monkeypatch.setattr("mobius.workflow.cancel._read_pid", fail_if_pid_read)
    monkeypatch.setattr("mobius.workflow.cancel._terminate_process", fail_if_signal_sent)

    result = cancel_run(paths, run_id, grace_period=0.01)

    assert result is CancelResult.ALREADY_FINISHED
    assert not run_paths.pid_file.exists()


def test_cancel_escalates_to_sigkill_marks_cancelled_and_removes_pid(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "home")
    run_id = "run_cancel"
    with EventStore(paths.event_store) as store:
        store.create_session(run_id, runtime="run", status="running")

    process = _start_sigterm_ignoring_process()
    run_paths = get_run_paths(paths, run_id)
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

    try:
        result = cancel_run(paths, run_id, grace_period=0.05)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert result is CancelResult.CANCELLED
    assert not run_paths.pid_file.exists()
    assert process.returncode == -signal.SIGKILL

    with EventStore(paths.event_store) as store:
        session = store._connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            (run_id,),
        ).fetchone()
        event_types = [event.type for event in store.read_events(run_id)]

    assert session["status"] == "cancelled"
    assert "run.cancelled" in event_types
