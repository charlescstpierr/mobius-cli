"""Run workflow execution helpers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from mobius.cli.main import ExitCode
from mobius.config import MobiusPaths
from mobius.persistence.event_store import EventStore
from mobius.workflow.ids import readable_session_id
from mobius.workflow.seed import SeedSpec, SeedSpecValidationError, load_seed_spec


@dataclass(frozen=True)
class RunPaths:
    """Filesystem paths for one run."""

    directory: Path
    pid_file: Path
    log_file: Path
    metadata_file: Path


@dataclass(frozen=True)
class PreparedRun:
    """A validated run ready to execute."""

    run_id: str
    spec_path: Path
    spec: SeedSpec
    paths: RunPaths


def prepare_run(paths: MobiusPaths, spec_path: Path) -> PreparedRun:
    """Validate a spec and create the run metadata directory."""
    resolved_spec_path = spec_path.expanduser().resolve()
    spec = load_seed_spec(resolved_spec_path)
    run_id = readable_session_id("run", spec.goal)
    run_paths = get_run_paths(paths, run_id)
    run_paths.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(run_paths.directory, 0o700)
    run_paths.metadata_file.write_text(
        json.dumps({"spec_path": str(resolved_spec_path)}, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(run_paths.metadata_file, 0o600)
    return PreparedRun(
        run_id=run_id,
        spec_path=resolved_spec_path,
        spec=spec,
        paths=run_paths,
    )


def get_run_paths(paths: MobiusPaths, run_id: str) -> RunPaths:
    """Return the run directory paths for ``run_id``."""
    directory = paths.state_dir / "runs" / run_id
    return RunPaths(
        directory=directory,
        pid_file=directory / "pid",
        log_file=directory / "log",
        metadata_file=directory / "metadata.json",
    )


def start_detached_worker(paths: MobiusPaths, prepared: PreparedRun) -> int:
    """Fork a detached worker process and write its PID file."""
    with EventStore(paths.event_store) as store:
        store.create_session(
            prepared.run_id,
            runtime="run",
            metadata={
                "spec_path": str(prepared.spec_path),
                "project_type": prepared.spec.project_type,
            },
            status="running",
        )
    prepared.paths.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with prepared.paths.log_file.open("ab") as log_file, Path(os.devnull).open("rb") as devnull:
        process = subprocess.Popen(
            ["mobius", "_worker", "run", prepared.run_id],
            stdin=devnull,
            stdout=devnull,
            stderr=log_file,
            start_new_session=True,
        )
    _write_pid(prepared.paths.pid_file, process.pid)
    return process.pid


def run_foreground(paths: MobiusPaths, prepared: PreparedRun) -> int:
    """Execute a run in the current process, streaming progress to stderr."""
    return execute_run(paths, prepared.run_id, stream_events=True)


def execute_run(paths: MobiusPaths, run_id: str, *, stream_events: bool) -> int:
    """Worker entry point for a prepared run."""
    run_paths = get_run_paths(paths, run_id)
    spec_path = _read_spec_path(run_paths)
    try:
        spec = load_seed_spec(spec_path)
    except SeedSpecValidationError as exc:
        _emit(stream_events, f"run.validation_failed {exc}")
        _cleanup_pid(run_paths.pid_file)
        return int(ExitCode.VALIDATION)

    interrupted = RunInterrupted(paths=paths, run_id=run_id, pid_file=run_paths.pid_file)
    signal.signal(signal.SIGTERM, interrupted.handle_sigterm)
    signal.signal(signal.SIGINT, interrupted.handle_sigint)

    try:
        with EventStore(paths.event_store) as store:
            store.create_session(
                run_id,
                runtime="run",
                metadata={"spec_path": str(spec_path), "project_type": spec.project_type},
                status="running",
            )
            _append_and_emit(
                store,
                run_id,
                "run.started",
                {"spec_path": str(spec_path), "goal": spec.goal},
                stream_events=stream_events,
            )
            _write_pid(run_paths.pid_file, os.getpid())
            _sleep_with_heartbeats(store, run_id, spec, stream_events=stream_events)
            _append_and_emit(
                store,
                run_id,
                "run.completed",
                {
                    "constraint_count": len(spec.constraints),
                    "success_criteria_count": len(spec.success_criteria),
                },
                stream_events=stream_events,
            )
            store.end_session(run_id, status="completed")
        return int(ExitCode.OK)
    finally:
        _cleanup_pid(run_paths.pid_file)


def mark_stale_run_if_needed(paths: MobiusPaths, run_id: str) -> None:
    """Mark a run crashed when a PID file points at a dead process."""
    run_paths = get_run_paths(paths, run_id)
    if not run_paths.pid_file.exists():
        return
    try:
        pid = int(run_paths.pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = -1
    if pid > 0 and _pid_is_live(pid):
        return
    _cleanup_pid(run_paths.pid_file)
    with EventStore(paths.event_store) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"reason": "stale pid file", "pid": pid},
            status="running",
        )
        store.append_event(run_id, "run.crashed", {"reason": "stale pid file", "pid": pid})
        store.end_session(run_id, status="crashed")


class RunInterrupted:
    """Signal handlers for a running worker."""

    def __init__(self, *, paths: MobiusPaths, run_id: str, pid_file: Path) -> None:
        self.paths = paths
        self.run_id = run_id
        self.pid_file = pid_file

    def handle_sigterm(self, _signum: int, _frame: object | None) -> NoReturn:
        """Handle graceful cancellation.

        The worker is the authority on ``run.cancelled``: it emits the
        event, updates the session status, and cleans up its PID file. The
        cancel command observes this rather than emitting its own event,
        which is how v0.1.4 avoids the duplicate-cancel bug from v0.1.3.
        """
        self._finish("cancelled", "run.cancelled")
        raise SystemExit(int(ExitCode.OK))

    def handle_sigint(self, _signum: int, _frame: object | None) -> NoReturn:
        """Handle interactive interruption."""
        self._finish("interrupted", "run.interrupted")
        sys.stderr.write("interrupted\n")
        raise SystemExit(int(ExitCode.INTERRUPTED))

    def _finish(self, status: str, event_type: str) -> None:
        with EventStore(self.paths.event_store) as store:
            # Idempotency: if the event has already been emitted (e.g. a
            # second SIGTERM lands while the handler is running), do not
            # append a duplicate.
            existing = [event.type for event in store.read_events(self.run_id)]
            if event_type not in existing:
                store.append_event(self.run_id, event_type, {"signal": status})
                store.end_session(self.run_id, status=status)
        _cleanup_pid(self.pid_file)


def _sleep_with_heartbeats(
    store: EventStore,
    run_id: str,
    spec: SeedSpec,
    *,
    stream_events: bool,
) -> None:
    heartbeat_count = max(3, min(10, len(spec.success_criteria) + len(spec.constraints)))
    for index in range(heartbeat_count):
        _append_and_emit(
            store,
            run_id,
            "run.progress",
            {"step": index + 1, "total": heartbeat_count},
            stream_events=stream_events,
        )
        time.sleep(0.2)


def _append_and_emit(
    store: EventStore,
    run_id: str,
    event_type: str,
    payload: dict[str, object],
    *,
    stream_events: bool,
) -> None:
    event = store.append_event(run_id, event_type, payload)
    _emit(stream_events, f"{event.created_at} {event.type} {event.payload}")


def _emit(stream_events: bool, message: str) -> None:
    if stream_events:
        sys.stderr.write(f"{message}\n")
        sys.stderr.flush()


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(f"{pid}\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(path)
    os.chmod(path, 0o600)


def _cleanup_pid(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def _read_spec_path(run_paths: RunPaths) -> Path:
    try:
        metadata = json.loads(run_paths.metadata_file.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"run metadata not found for {run_paths.directory.name}: {exc}"
        raise SeedSpecValidationError(msg) from exc
    value = metadata.get("spec_path")
    if not isinstance(value, str) or not value:
        msg = f"run metadata missing spec_path for {run_paths.directory.name}"
        raise SeedSpecValidationError(msg)
    return Path(value)


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
