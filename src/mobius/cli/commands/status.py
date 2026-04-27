"""Handlers for the Mobius status command."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


class StatusOutput(BaseModel):
    """Structured status output for store-level status checks."""

    model_config = ConfigDict(extra="forbid")

    event_store: str
    read_only: bool
    migrations_applied: bool
    integrity_check: str
    event_count: int


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
    with EventStore(paths.event_store, read_only=read_only) as store:
        migration_count = store.connection.execute(
            "SELECT count(*) FROM schema_migrations"
        ).fetchone()
        event_count = store.connection.execute("SELECT count(*) FROM events").fetchone()
        payload = StatusOutput(
            event_store=str(paths.event_store),
            read_only=read_only,
            migrations_applied=int(migration_count[0]) > 0,
            integrity_check=store.integrity_check(),
            event_count=int(event_count[0]),
        )

    if context.json_output or json_output:
        output.write_json(payload.model_dump_json())
        return

    if run_id is None:
        output.write_line(f"event_store={payload.event_store}")
        output.write_line(f"read_only={str(payload.read_only).lower()}")
        output.write_line(f"migrations_applied={str(payload.migrations_applied).lower()}")
        output.write_line(f"integrity_check={payload.integrity_check}")
        output.write_line(f"event_count={payload.event_count}")
        return

    output.write_line(f"run_id={run_id}")
    output.write_line(f"event_store={payload.event_store}")
    output.write_line(f"read_only={str(payload.read_only).lower()}")
