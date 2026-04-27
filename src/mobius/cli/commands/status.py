"""Handlers for the Mobius status command."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.run import mark_stale_run_if_needed


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
) -> None:
    """Open the event store and report a lightweight status snapshot.

    ``run_id`` is accepted for forward compatibility with the M2 status command,
    but M1 status currently reports store health only.
    """
    paths = get_paths(context.mobius_home)
    if run_id is not None and not read_only:
        mark_stale_run_if_needed(paths, run_id)

    with EventStore(paths.event_store, read_only=read_only) as store:
        if run_id is not None:
            session = store.connection.execute(
                """
                SELECT session_id, started_at, ended_at, status
                FROM sessions
                WHERE session_id = ?
                """,
                (run_id,),
            ).fetchone()
            if session is None:
                output.write_error_line(f"run not found: {run_id}")
                raise SystemExit(int(ExitCode.NOT_FOUND))
            event = store.connection.execute(
                """
                SELECT created_at
                FROM events
                WHERE aggregate_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            last_event_at = str(event["created_at"] if event is not None else session["started_at"])
            run_payload = RunStatusOutput(
                run_id=str(session["session_id"]),
                state=str(session["status"]),
                started_at=str(session["started_at"]),
                last_event_at=last_event_at,
            )
            if context.json_output or json_output:
                output.write_json(run_payload.model_dump_json())
                return
            output.write_line(f"run_id={run_payload.run_id}")
            output.write_line(f"state={run_payload.state}")
            output.write_line(f"started_at={run_payload.started_at}")
            output.write_line(f"last_event_at={run_payload.last_event_at}")
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

    if context.json_output or json_output:
        output.write_json(status_payload.model_dump_json())
        return

    if run_id is None:
        output.write_line(f"event_store={status_payload.event_store}")
        output.write_line(f"read_only={str(status_payload.read_only).lower()}")
        output.write_line(f"migrations_applied={str(status_payload.migrations_applied).lower()}")
        output.write_line(f"integrity_check={status_payload.integrity_check}")
        output.write_line(f"event_count={status_payload.event_count}")
        return
