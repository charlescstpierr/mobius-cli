"""Handlers for the Mobius status command."""

from __future__ import annotations

import time
from pathlib import Path
from typing import NoReturn

from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.cli.session_inspector import EventStoreSessionAdapter, RunStatus, SessionInspector
from mobius.config import MobiusPaths, get_paths
from mobius.persistence.event_store import EventRecord, EventStore
from mobius.workflow.evolve import get_evolution_paths
from mobius.workflow.run import get_run_paths

_FOLLOW_INTERVAL_SECONDS = 0.2
_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})


class StatusOutput(BaseModel):
    """Structured status output for store-level status checks."""

    model_config = ConfigDict(extra="forbid")

    event_store: str
    read_only: bool
    migrations_applied: bool
    integrity_check: str
    event_count: int


class RunStatusOutput(BaseModel):
    """Structured status output for a run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: str
    started_at: str
    last_event_at: str


def run(
    context: CliContext,
    run_id: str | None = None,
    *,
    read_only: bool = False,
    json_output: bool = False,
    follow: bool = False,
) -> None:
    """Open the event store and report either store health or run status."""
    paths = get_paths(context.mobius_home)
    inspector = _session_inspector(paths)
    if follow:
        if run_id is None:
            output.write_error_line("status --follow requires a run id")
            raise SystemExit(int(ExitCode.USAGE))
        with EventStore(paths.event_store, read_only=read_only):
            run_id = _resolve_run_id(inspector, run_id)
        _follow_run(paths.event_store, paths, inspector, run_id=run_id, read_only=read_only)
        return

    if run_id is not None and not read_only:
        with EventStore(paths.event_store):
            run_id = _resolve_run_id(inspector, run_id)
        inspector.mark_stale_session_if_needed(run_id)

    with EventStore(paths.event_store, read_only=read_only) as store:
        if run_id is not None:
            run_id = _resolve_run_id(inspector, run_id)
            run_status = inspector.read_run_status(run_id)
            run_payload = _to_run_status_output(run_status) if run_status is not None else None
            if run_payload is None:
                _raise_not_found(run_id)
            formatter = get_formatter(context, json_output=json_output)
            formatter.emit(run_payload, text=lambda: _write_run_markdown(run_payload))
            return

        migration_count = store.connection.execute(
            "SELECT count(*) FROM schema_migrations"
        ).fetchone()
        event_count = store.connection.execute("SELECT count(*) FROM events").fetchone()
        status_payload = StatusOutput(
            event_store=str(paths.event_store),
            read_only=read_only,
            migrations_applied=int(migration_count[0]) > 0,
            integrity_check=store.integrity_check(),
            event_count=int(event_count[0]),
        )

    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(status_payload, text=lambda: _write_store_status(status_payload))
    return


def _follow_run(
    event_store_path: Path,
    paths: MobiusPaths,
    inspector: SessionInspector,
    *,
    run_id: str,
    read_only: bool,
) -> None:
    cursor = 0
    saw_session = False
    pending_run_files = _has_pending_run_files(paths, run_id)

    while True:
        if not read_only:
            inspector.mark_stale_session_if_needed(run_id)

        with EventStore(event_store_path, read_only=read_only) as store:
            run_status = inspector.read_run_status(run_id)
            run_payload = _to_run_status_output(run_status) if run_status is not None else None
            if run_payload is None:
                if saw_session or not pending_run_files:
                    _raise_not_found(run_id)
                time.sleep(_FOLLOW_INTERVAL_SECONDS)
                continue

            saw_session = True
            events = _read_events_after_cursor(store, run_id, cursor)
            for event in events:
                output.write_line(_format_event_delta(event))
                cursor = max(cursor, event.sequence)

            if run_payload.state in _TERMINAL_STATES:
                _write_run_markdown(run_payload)
                return

        time.sleep(_FOLLOW_INTERVAL_SECONDS)


def _session_inspector(paths: MobiusPaths) -> SessionInspector:
    return SessionInspector(
        state_dir=paths.state_dir,
        adapter=EventStoreSessionAdapter(paths.event_store),
    )


def _to_run_status_output(status: RunStatus | None) -> RunStatusOutput | None:
    if status is None:
        return None
    return RunStatusOutput(
        run_id=status.run_id,
        state=status.state,
        started_at=status.started_at,
        last_event_at=status.last_event_at,
    )


def _resolve_run_id(inspector: SessionInspector, run_id: str) -> str:
    resolved = inspector.resolve_run_id(run_id)
    if resolved is None:
        _raise_not_found(run_id)
    if not isinstance(resolved, str):
        candidates = ", ".join(resolved)
        output.write_error_line(f"ambiguous run prefix: {run_id}; candidates: {candidates}")
        raise SystemExit(int(ExitCode.USAGE))
    return resolved


def _read_events_after_cursor(
    store: EventStore,
    run_id: str,
    cursor: int,
) -> list[EventRecord]:
    rows = store.connection.execute(
        """
        SELECT event_id, aggregate_id, sequence, type, payload, created_at
        FROM events
        WHERE aggregate_id = ? AND sequence > ?
        ORDER BY sequence ASC
        """,
        (run_id, cursor),
    ).fetchall()
    return [
        EventRecord(
            event_id=str(row["event_id"]),
            aggregate_id=str(row["aggregate_id"]),
            sequence=int(row["sequence"]),
            type=str(row["type"]),
            payload=str(row["payload"]),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]


def _write_run_markdown(run_payload: RunStatusOutput) -> None:
    output.write_line(f"# Run {run_payload.run_id}")
    output.write_line("")
    output.write_line("| Field | Value |")
    output.write_line("| --- | --- |")
    output.write_line(f"| State | {run_payload.state} |")
    output.write_line(f"| Started at | {run_payload.started_at} |")
    output.write_line(f"| Last event at | {run_payload.last_event_at} |")


def _write_store_status(status_payload: StatusOutput) -> None:
    output.write_line(f"event_store={status_payload.event_store}")
    output.write_line(f"read_only={str(status_payload.read_only).lower()}")
    output.write_line(f"migrations_applied={str(status_payload.migrations_applied).lower()}")
    output.write_line(f"integrity_check={status_payload.integrity_check}")
    output.write_line(f"event_count={status_payload.event_count}")


def _format_event_delta(event: EventRecord) -> str:
    return (
        f"- `{event.created_at}` seq={event.sequence} type={event.type} payload=`{event.payload}`"
    )


def _has_pending_run_files(paths: MobiusPaths, run_id: str) -> bool:
    run_paths = get_run_paths(paths, run_id)
    evolution_paths = get_evolution_paths(paths, run_id)
    return (
        run_paths.metadata_file.exists()
        or run_paths.pid_file.exists()
        or evolution_paths.metadata_file.exists()
        or evolution_paths.pid_file.exists()
    )


def mark_stale_session_if_needed(paths: MobiusPaths, session_id: str) -> None:
    """Mark any detached run/evolution crashed when its PID file is stale."""
    _session_inspector(paths).mark_stale_session_if_needed(session_id)


def _raise_not_found(run_id: str) -> NoReturn:
    output.write_error_line(f"run not found: {run_id}")
    raise SystemExit(int(ExitCode.NOT_FOUND))
