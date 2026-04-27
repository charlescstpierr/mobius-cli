"""Cancellation helpers for detached Mobius runs."""

from __future__ import annotations

import os
import signal
import time
from contextlib import suppress
from enum import StrEnum
from pathlib import Path

from mobius.config import MobiusPaths
from mobius.persistence.event_store import EventStore
from mobius.workflow.evolve import get_evolution_paths
from mobius.workflow.run import get_run_paths

_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})


class CancelResult(StrEnum):
    """Possible outcomes from a cancellation request."""

    CANCELLED = "cancelled"
    ALREADY_FINISHED = "already_finished"
    NOT_FOUND = "not_found"


def cancel_run(paths: MobiusPaths, run_id: str, *, grace_period: float = 10.0) -> CancelResult:
    """Cancel a run by PID file, escalating from SIGTERM to SIGKILL if necessary."""
    session = _read_session(paths, run_id)
    if session is None:
        return CancelResult.NOT_FOUND
    runtime, session_status = session
    pid_file = _pid_file_for_runtime(paths, run_id, runtime)
    if session_status in _TERMINAL_STATES:
        _cleanup_pid_file(pid_file)
        return CancelResult.ALREADY_FINISHED

    if not pid_file.exists():
        _mark_cancelled(
            paths,
            run_id,
            runtime=runtime,
            pid=None,
            escalated=False,
            reason="missing pid file",
        )
        return CancelResult.CANCELLED

    pid = _read_pid(pid_file)
    if pid is None:
        _cleanup_pid_file(pid_file)
        _mark_cancelled(
            paths,
            run_id,
            runtime=runtime,
            pid=None,
            escalated=False,
            reason="invalid pid file",
        )
        return CancelResult.CANCELLED

    if not _pid_is_live(pid):
        _cleanup_pid_file(pid_file)
        _mark_cancelled(
            paths,
            run_id,
            runtime=runtime,
            pid=pid,
            escalated=False,
            reason="stale pid file",
        )
        return CancelResult.CANCELLED

    escalated = _terminate_process(pid, grace_period=grace_period)
    _cleanup_pid_file(pid_file)
    _mark_cancelled(paths, run_id, runtime=runtime, pid=pid, escalated=escalated)
    return CancelResult.CANCELLED


def _terminate_process(pid: int, *, grace_period: float) -> bool:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_period)
    while time.monotonic() < deadline:
        if not _pid_is_live(pid):
            return False
        time.sleep(0.05)
    if _pid_is_live(pid):
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not _pid_is_live(pid):
                return True
            time.sleep(0.05)
        return True
    return False


def _mark_cancelled(
    paths: MobiusPaths,
    run_id: str,
    *,
    runtime: str,
    pid: int | None,
    escalated: bool,
    reason: str = "cancel requested",
) -> None:
    with EventStore(paths.event_store) as store:
        store.create_session(
            run_id,
            runtime=runtime,
            metadata={"reason": reason},
            status="running",
        )
        store.append_event(run_id, f"{runtime}.cancelled", {"pid": pid, "escalated": escalated})
        store.end_session(run_id, status="cancelled")


def _read_session(paths: MobiusPaths, run_id: str) -> tuple[str, str] | None:
    if not paths.event_store.exists():
        return None
    with EventStore(paths.event_store) as store:
        row = store._connection.execute(
            "SELECT runtime, status FROM sessions WHERE session_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["runtime"]), str(row["status"])


def _pid_file_for_runtime(paths: MobiusPaths, session_id: str, runtime: str) -> Path:
    if runtime == "evolution":
        return get_evolution_paths(paths, session_id).pid_file
    return get_run_paths(paths, session_id).pid_file


def _read_pid(pid_file: os.PathLike[str]) -> int | None:
    try:
        pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _cleanup_pid_file(pid_file: os.PathLike[str]) -> None:
    with suppress(FileNotFoundError):
        os.unlink(pid_file)


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
