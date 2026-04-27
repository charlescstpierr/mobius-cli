"""Cancellation helpers for detached Mobius runs.

De-duplication contract (v0.1.4): the **worker** is the sole authority on
emitting the ``<runtime>.cancelled`` event. When ``mobius cancel`` is
invoked it:

1. Sends SIGTERM to the worker (if alive).
2. Waits for the worker to exit.
3. Synthesizes a ``<runtime>.cancelled`` event itself only when the worker
   was already dead/missing/escalated to SIGKILL — i.e. when the worker
   could not have written the event.

This guarantees exactly one cancel event per cancel call regardless of
whether SIGTERM was the trigger.
"""

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
    """Cancel a run; emit at most one ``<runtime>.cancelled`` event."""
    session = _read_session(paths, run_id)
    if session is None:
        return CancelResult.NOT_FOUND
    runtime, session_status = session
    pid_file = _pid_file_for_runtime(paths, run_id, runtime)
    if session_status in _TERMINAL_STATES:
        _cleanup_pid_file(pid_file)
        return CancelResult.ALREADY_FINISHED

    if not pid_file.exists():
        _maybe_emit_cancel(
            paths, run_id, runtime, pid=None, escalated=False, reason="missing pid file"
        )
        return CancelResult.CANCELLED

    pid = _read_pid(pid_file)
    if pid is None:
        _cleanup_pid_file(pid_file)
        _maybe_emit_cancel(
            paths, run_id, runtime, pid=None, escalated=False, reason="invalid pid file"
        )
        return CancelResult.CANCELLED

    if not _pid_is_live(pid):
        _cleanup_pid_file(pid_file)
        _maybe_emit_cancel(
            paths, run_id, runtime, pid=pid, escalated=False, reason="stale pid file"
        )
        return CancelResult.CANCELLED

    escalated = _terminate_process(pid, grace_period=grace_period)
    _cleanup_pid_file(pid_file)
    # Give the worker's SIGTERM handler a brief grace window to flush its
    # ``<runtime>.cancelled`` event. If absent, we synthesize one.
    _maybe_emit_cancel(
        paths,
        run_id,
        runtime,
        pid=pid,
        escalated=escalated,
        reason="terminated by SIGKILL" if escalated else "terminated by SIGTERM",
        wait_for_worker=not escalated,
    )
    return CancelResult.CANCELLED


def _terminate_process(pid: int, *, grace_period: float) -> bool:
    """Send SIGTERM and escalate to SIGKILL if needed. Returns True if escalated."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    deadline = time.monotonic() + max(0.0, grace_period)
    while time.monotonic() < deadline:
        if not _pid_is_live(pid):
            return False
        time.sleep(0.05)
    if _pid_is_live(pid):
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not _pid_is_live(pid):
                break
            time.sleep(0.05)
        return True
    return False


def _maybe_emit_cancel(
    paths: MobiusPaths,
    run_id: str,
    runtime: str,
    *,
    pid: int | None,
    escalated: bool,
    reason: str,
    wait_for_worker: bool = False,
) -> None:
    """Emit ``<runtime>.cancelled`` only if the worker hasn't already.

    ``wait_for_worker`` polls the event store for up to one second to give
    a SIGTERM-ed worker time to flush its event; outside that window we
    synthesize one ourselves.
    """
    event_type = f"{runtime}.cancelled"
    if wait_for_worker and _wait_for_event(paths, run_id, event_type, deadline_seconds=1.0):
        _ensure_status_cancelled(paths, run_id)
        return
    if _has_event(paths, run_id, event_type):
        _ensure_status_cancelled(paths, run_id)
        return
    with EventStore(paths.event_store) as store:
        store.create_session(run_id, runtime=runtime, metadata={"reason": reason}, status="running")
        store.append_event(run_id, event_type, {"pid": pid, "escalated": escalated})
        store.end_session(run_id, status="cancelled")


def _wait_for_event(
    paths: MobiusPaths, run_id: str, event_type: str, *, deadline_seconds: float
) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if _has_event(paths, run_id, event_type):
            return True
        time.sleep(0.05)
    return False


def _has_event(paths: MobiusPaths, run_id: str, event_type: str) -> bool:
    if not paths.event_store.exists():
        return False
    with EventStore(paths.event_store, read_only=True) as store:
        row = store.connection.execute(
            "SELECT 1 FROM events WHERE aggregate_id = ? AND type = ? LIMIT 1",
            (run_id, event_type),
        ).fetchone()
    return row is not None


def _ensure_status_cancelled(paths: MobiusPaths, run_id: str) -> None:
    if not paths.event_store.exists():
        return
    with EventStore(paths.event_store) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?", (run_id,)
        ).fetchone()
        if row is not None and row["status"] != "cancelled":
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
