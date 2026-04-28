"""Handler for the ``mobius runs ls`` command."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


class RunRow(BaseModel):
    """One row in the runs listing."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    title: str
    status: str
    started: str
    duration: str
    criteria: str
    criteria_passed: int
    criteria_failed: int
    criteria_unverified: int
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

    from rich.table import Table

    table = Table(show_header=True, header_style="bold", width=140)
    table.add_column("ID", max_width=28, overflow="ellipsis")
    table.add_column("Title", max_width=40, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("Started", no_wrap=True)
    table.add_column("Duration", justify="right", no_wrap=True)
    table.add_column("Criteria", justify="right", no_wrap=True)
    for row in rows:
        table.add_row(
            row.run_id,
            row.title,
            _colored_status(row.status),
            row.started,
            row.duration,
            row.criteria,
        )
    output.write_rich(table, width=160)


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
            SELECT s.session_id, s.runtime, s.status, s.started_at, s.ended_at,
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
        events_by_run = {
            str(row["session_id"]): store.read_events(str(row["session_id"])) for row in rows
        }
    return [
        _row_from_session(
            row={
                "session_id": str(row["session_id"]),
                "runtime": str(row["runtime"]),
                "status": str(row["status"]),
                "started_at": str(row["started_at"]),
                "ended_at": None if row["ended_at"] is None else str(row["ended_at"]),
                "last_event_at": str(row["last_event_at"]),
            },
            events=events_by_run[str(row["session_id"])],
        )
        for row in rows
    ]


def _exists(path: object) -> bool:
    from pathlib import Path

    return Path(str(path)).exists()


def _row_from_session(*, row: dict[str, str | None], events: Sequence[object]) -> RunRow:
    run_id = str(row["session_id"])
    status = str(row["status"])
    started_at = str(row["started_at"])
    last_event_at = str(row["last_event_at"])
    ended_at = row["ended_at"]
    passed, failed, unverified = _criteria_counts(status, events)
    return RunRow(
        run_id=run_id,
        title=_title_from_events(events),
        status=status,
        started=started_at,
        duration=_format_duration(started_at, ended_at or last_event_at),
        criteria=f"{passed}/{failed}/{unverified}",
        criteria_passed=passed,
        criteria_failed=failed,
        criteria_unverified=unverified,
        runtime=str(row["runtime"]),
        state=status,
        started_at=started_at,
        last_event_at=last_event_at,
    )


def _title_from_events(events: Sequence[object]) -> str:
    for event in events:
        payload = _payload_data(event)
        if getattr(event, "type", "") == "run.started":
            title = payload.get("title")
            if isinstance(title, str) and title.strip():
                return title
            goal = payload.get("goal")
            if isinstance(goal, str) and goal.strip():
                return goal
    return "(untitled)"


def _criteria_counts(status: str, events: Sequence[object]) -> tuple[int, int, int]:
    qa_counts = _latest_qa_counts(events)
    if qa_counts is not None:
        return qa_counts

    total = _success_criteria_count(events)
    if total == 0:
        return (0, 0, 0)
    if status == "completed":
        return (total, 0, 0)
    if status in {"failed", "crashed", "cancelled", "interrupted"}:
        return (0, total, 0)
    return (0, 0, total)


def _latest_qa_counts(events: Sequence[object]) -> tuple[int, int, int] | None:
    for event in reversed(events):
        if not str(getattr(event, "type", "")).startswith("qa."):
            continue
        payload = _payload_data(event)
        summary = payload.get("summary")
        if isinstance(summary, dict):
            payload = summary
        passed = _int_from_payload(payload, "passed")
        failed = _int_from_payload(payload, "failed")
        unverified = _int_from_payload(payload, "unverified")
        if passed is not None and failed is not None and unverified is not None:
            return (passed, failed, unverified)
    return None


def _success_criteria_count(events: Sequence[object]) -> int:
    for event in reversed(events):
        payload = _payload_data(event)
        count = _int_from_payload(payload, "success_criteria_count")
        if count is not None:
            return count
    return 0


def _payload_data(event: object) -> dict[str, Any]:
    payload_data = getattr(event, "payload_data", None)
    if isinstance(payload_data, dict):
        return payload_data
    payload = getattr(event, "payload", "{}")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _int_from_payload(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _format_duration(started_at: str, ended_at: str) -> str:
    started = _parse_utc(started_at)
    ended = _parse_utc(ended_at)
    if started is None or ended is None:
        return "unknown"
    seconds = max(0.0, (ended - started).total_seconds())
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, remaining = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _colored_status(status: str) -> str:
    colors = {
        "completed": "green",
        "running": "cyan",
        "failed": "red",
        "crashed": "red",
        "cancelled": "yellow",
        "interrupted": "yellow",
    }
    color = colors.get(status, "white")
    return f"[{color}]{status}[/{color}]"
