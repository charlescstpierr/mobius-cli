"""Lineage projection and replay hashing for Mobius aggregates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventStore


class LineageNode(BaseModel):
    """One aggregate in a lineage projection."""

    model_config = ConfigDict(extra="forbid")

    aggregate_id: str
    runtime: str
    status: str
    phase: str
    depth: int
    parent_id: str | None = None


class LineageOutput(BaseModel):
    """Structured lineage output for one aggregate."""

    model_config = ConfigDict(extra="forbid")

    aggregate_id: str
    current: LineageNode
    ancestors: list[LineageNode]
    descendants: list[LineageNode]


def build_lineage(event_store_path: Path, aggregate_id: str) -> LineageOutput | None:
    """Build ancestors and descendants for ``aggregate_id`` from session metadata."""
    with EventStore(event_store_path) as store:
        sessions = _read_sessions(store)
    current = sessions.get(aggregate_id)
    if current is None:
        return None

    ancestors = _build_ancestors(sessions, aggregate_id)
    descendants = _build_descendants(sessions, aggregate_id)
    return LineageOutput(
        aggregate_id=aggregate_id,
        current=_to_node(current, depth=0),
        ancestors=ancestors,
        descendants=descendants,
    )


def replay_hash_for_aggregate(event_store_path: Path, aggregate_id: str) -> str | None:
    """Return a deterministic replay hash for an existing aggregate, or None."""
    with EventStore(event_store_path) as store:
        session = _read_session(store, aggregate_id)
        events = store.read_events(aggregate_id)
        if session is None and not events:
            return None
        return store.replay_hash(aggregate_id)


def _read_sessions(store: EventStore) -> dict[str, dict[str, Any]]:
    rows = store.connection.execute(
        """
        SELECT session_id, runtime, status, metadata
        FROM sessions
        ORDER BY started_at ASC, session_id ASC
        """
    ).fetchall()
    return {
        str(row["session_id"]): {
            "session_id": str(row["session_id"]),
            "runtime": str(row["runtime"]),
            "status": str(row["status"]),
            "metadata": _decode_metadata(str(row["metadata"])),
        }
        for row in rows
    }


def _read_session(store: EventStore, aggregate_id: str) -> Any | None:
    return store.connection.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?",
        (aggregate_id,),
    ).fetchone()


def _build_ancestors(
    sessions: dict[str, dict[str, Any]],
    aggregate_id: str,
) -> list[LineageNode]:
    ancestors_from_parent: list[LineageNode] = []
    seen = {aggregate_id}
    parent_id = _parent_id(sessions[aggregate_id])
    depth = -1
    while parent_id is not None and parent_id not in seen:
        parent = sessions.get(parent_id)
        if parent is None:
            break
        seen.add(parent_id)
        ancestors_from_parent.append(_to_node(parent, depth=depth))
        parent_id = _parent_id(parent)
        depth -= 1
    return list(reversed(ancestors_from_parent))


def _build_descendants(
    sessions: dict[str, dict[str, Any]],
    aggregate_id: str,
) -> list[LineageNode]:
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for session in sessions.values():
        parent_id = _parent_id(session)
        if parent_id is not None:
            children_by_parent.setdefault(parent_id, []).append(session)

    descendants: list[LineageNode] = []
    seen = {aggregate_id}

    def visit(parent_id: str, depth: int) -> None:
        for child in children_by_parent.get(parent_id, []):
            child_id = str(child["session_id"])
            if child_id in seen:
                continue
            seen.add(child_id)
            descendants.append(_to_node(child, depth=depth))
            visit(child_id, depth + 1)

    visit(aggregate_id, 1)
    return descendants


def _to_node(session: dict[str, Any], *, depth: int) -> LineageNode:
    metadata = session["metadata"]
    if not isinstance(metadata, dict):
        metadata = {}
    return LineageNode(
        aggregate_id=str(session["session_id"]),
        runtime=str(session["runtime"]),
        status=str(session["status"]),
        phase=_phase_for_session(str(session["runtime"]), metadata),
        depth=depth,
        parent_id=_parent_id(session),
    )


def _parent_id(session: dict[str, Any]) -> str | None:
    metadata = session.get("metadata")
    if not isinstance(metadata, dict):
        return None
    for key in ("source_run_id", "source_id", "parent_id", "from_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _phase_for_session(runtime: str, metadata: dict[str, Any]) -> str:
    for key in ("double_diamond_phase", "phase"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return {
        "interview": "discover",
        "seed": "define",
        "run": "deliver",
        "evolution": "evolve",
    }.get(runtime, "unknown")


def _decode_metadata(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}
