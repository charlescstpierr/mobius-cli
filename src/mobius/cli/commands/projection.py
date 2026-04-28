"""Handler for Mobius projection cache commands."""

from __future__ import annotations

import json

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths


def rebuild(
    context: CliContext,
    *,
    from_event_id: str | None = None,
    json_output: bool = False,
) -> None:
    """Rebuild the projection cache by replaying persisted events."""
    from mobius.persistence.event_store import EventStore, iso8601_utc_now
    from mobius.persistence.projections import rebuild_projection

    paths = get_paths(context.mobius_home)
    try:
        with EventStore(paths.event_store) as store:
            with store.transaction() as connection:
                _snapshot, events_replayed, duration_ms = rebuild_projection(
                    connection,
                    from_event_id=from_event_id,
                )
            rebuilt_at = iso8601_utc_now()
            event = store.append_event(
                "mobius.projection.rebuilds",
                "projection.rebuilt",
                {
                    "events_replayed": events_replayed,
                    "duration_ms": duration_ms,
                    "from_event_id": from_event_id,
                    "rebuilt_at": rebuilt_at,
                },
            )
    except ValueError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.NOT_FOUND)) from exc

    payload = {
        "event_id": event.event_id,
        "events_replayed": events_replayed,
        "duration_ms": duration_ms,
        "from_event_id": from_event_id,
        "rebuilt_at": rebuilt_at,
    }
    if context.json_output or json_output:
        output.write_json(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        output.write_line(
            f"projection rebuilt: events_replayed={events_replayed} "
            f"duration_ms={duration_ms}"
        )
