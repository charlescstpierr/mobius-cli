"""Handler for the ``mobius runs ls`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


class RunRow(BaseModel):
    """One row in the runs listing."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    runtime: str
    state: str
    started_at: str
    last_event_at: str


class RunsListing(BaseModel):
    """JSON envelope for the runs listing."""

    model_config = ConfigDict(extra="forbid")

    runs: list[RunRow]


@dataclass(frozen=True)
class _ListOptions:
    limit: int
    show_all: bool
    runtime: str | None


def ls(
    context: CliContext,
    *,
    limit: int = 20,
    show_all: bool = False,
    runtime: str | None = None,
    json_output: bool = False,
) -> None:
    """List runs (and optionally evolutions) recorded in the event store."""
    paths = get_paths(context.mobius_home)
    options = _ListOptions(limit=limit, show_all=show_all, runtime=runtime)
    rows = _read_rows(paths.event_store, options)

    if context.json_output or json_output:
        output.write_json(RunsListing(runs=rows).model_dump_json())
        return

    if not rows:
        output.write_line("(no runs found)")
        return

    output.write_line("| Run id | Runtime | State | Started at | Last event |")
    output.write_line("| --- | --- | --- | --- | --- |")
    for row in rows:
        output.write_line(
            f"| {row.run_id} | {row.runtime} | {row.state} | "
            f"{row.started_at} | {row.last_event_at} |"
        )


def _read_rows(event_store_path: Path, options: _ListOptions) -> list[RunRow]:
    if not event_store_path or not _exists(event_store_path):
        return []
    with EventStore(event_store_path, read_only=True) as store:
        params: list[object] = []
        clauses: list[str] = []
        if not options.show_all:
            clauses.append("runtime IN ('run', 'evolution')")
        if options.runtime is not None:
            clauses.append("runtime = ?")
            params.append(options.runtime)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = store.connection.execute(
            f"""
            SELECT s.session_id, s.runtime, s.status, s.started_at,
                   COALESCE(
                       (SELECT MAX(created_at) FROM events
                        WHERE aggregate_id = s.session_id),
                       s.started_at
                   ) AS last_event_at
            FROM sessions s
            {where}
            ORDER BY s.started_at DESC
            LIMIT ?
            """,
            (*params, max(1, options.limit)),
        ).fetchall()
    return [
        RunRow(
            run_id=str(row["session_id"]),
            runtime=str(row["runtime"]),
            state=str(row["status"]),
            started_at=str(row["started_at"]),
            last_event_at=str(row["last_event_at"]),
        )
        for row in rows
    ]


def _exists(path: object) -> bool:
    from pathlib import Path

    return Path(str(path)).exists()
