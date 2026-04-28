"""Best-effort aggregate projection cache for Mobius events."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping
from typing import Any, Protocol

from mobius.persistence.event_store import EventRecord, iso8601_utc_now

PROJECTION_AGGREGATE_ID = "mobius.projection.cache"
PROJECTION_AGGREGATE_TYPE = "projection.snapshot"


class ProjectionUpdater(Protocol):
    """Update a cached projection snapshot from one event."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the updated snapshot for ``event``."""


class QAProjectionUpdater:
    """Project QA proof and verification facts."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = _copy_snapshot(current_snapshot)
        if event.type == "qa.verification_executed":
            snapshot["last_qa_timestamp"] = event.created_at
            return _mark_fresh(snapshot, event)
        if event.type != "qa.proof_collected":
            return _mark_fresh(snapshot, event)

        payload = _payload_object(event)
        snapshot["last_qa_timestamp"] = event.created_at
        snapshot["proofs_collected"] = int(snapshot.get("proofs_collected", 0)) + 1

        criterion_ref = str(payload.get("criterion_ref", "")).strip()
        if criterion_ref:
            proofs_by_criterion = _nested_count_map(snapshot, "proofs_by_criterion")
            proofs_by_criterion[criterion_ref] = proofs_by_criterion.get(criterion_ref, 0) + 1
            snapshot["proofs_by_criterion"] = dict(sorted(proofs_by_criterion.items()))

            criteria_summary = _criteria_summary(snapshot)
            exit_code = payload.get("exit_code")
            verdict = "pass" if exit_code == 0 and not payload.get("timed_out") else "fail"
            criteria_summary["by_criterion"][criterion_ref] = verdict
            criteria_summary["passed"] = sum(
                1 for value in criteria_summary["by_criterion"].values() if value == "pass"
            )
            criteria_summary["failed"] = sum(
                1 for value in criteria_summary["by_criterion"].values() if value == "fail"
            )
            criteria_summary["unverified"] = sum(
                1
                for value in criteria_summary["by_criterion"].values()
                if value == "unverified"
            )
            snapshot["criteria_summary"] = criteria_summary

        return _mark_fresh(snapshot, event)


class SpecProjectionUpdater:
    """Project static grade facts."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = _copy_snapshot(current_snapshot)
        if event.type == "spec.grade_assigned":
            payload = _payload_object(event)
            snapshot["last_grade"] = {
                "grade": payload.get("grade"),
                "criteria_met": payload.get("criteria_met"),
                "criteria_total": payload.get("criteria_total"),
                "assigned_at": event.created_at,
            }
        if event.type in {"seed.completed", "run.started"}:
            payload = _payload_object(event)
            if payload.get("goal") is not None:
                current_spec = dict(snapshot.get("current_spec", {}))
                current_spec["goal"] = payload.get("goal")
                if payload.get("owner") is not None:
                    current_spec["owner"] = payload.get("owner")
                snapshot["current_spec"] = current_spec
        return _mark_fresh(snapshot, event)


class RunProjectionUpdater:
    """Project latest run status facts."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = _copy_snapshot(current_snapshot)
        latest_run = dict(snapshot.get("latest_run", {}))
        if event.type == "run.started":
            payload = _payload_object(event)
            latest_run = {
                "id": event.aggregate_id,
                "title": payload.get("title") or payload.get("goal") or event.aggregate_id,
                "status": "running",
                "started_at": event.created_at,
            }
        elif event.type in {
            "run.completed",
            "run.failed",
            "run.crashed",
            "run.cancelled",
            "run.interrupted",
        }:
            if latest_run.get("id") != event.aggregate_id:
                latest_run["id"] = event.aggregate_id
            latest_run["status"] = event.type.removeprefix("run.")
            latest_run["ended_at"] = event.created_at
        if latest_run:
            snapshot["latest_run"] = latest_run
        return _mark_fresh(snapshot, event)


class HandoffProjectionUpdater:
    """Project handoff completeness facts."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = _copy_snapshot(current_snapshot)
        if event.type == "handoff.generated":
            payload = _payload_object(event)
            snapshot["last_handoff"] = {
                "agent": payload.get("agent"),
                "template_version": payload.get("template_version"),
                "generated_at": event.created_at,
            }
        return _mark_fresh(snapshot, event)


ProjectionRegistry = dict[str, ProjectionUpdater]

DEFAULT_REGISTRY: ProjectionRegistry = {
    "qa.": QAProjectionUpdater(),
    "spec.": SpecProjectionUpdater(),
    "seed.": SpecProjectionUpdater(),
    "run.": RunProjectionUpdater(),
    "handoff.": HandoffProjectionUpdater(),
}


def register_projection(
    event_type_prefix: str,
    updater: ProjectionUpdater,
    registry: ProjectionRegistry | None = None,
) -> ProjectionUpdater | None:
    """Register ``updater`` for ``event_type_prefix`` and return any previous updater."""
    target = DEFAULT_REGISTRY if registry is None else registry
    normalized = _normalize_prefix(event_type_prefix)
    previous = target.get(normalized)
    target[normalized] = updater
    return previous


def unregister_projection(
    event_type_prefix: str,
    registry: ProjectionRegistry | None = None,
) -> ProjectionUpdater | None:
    """Remove and return the updater for ``event_type_prefix`` if present."""
    target = DEFAULT_REGISTRY if registry is None else registry
    return target.pop(_normalize_prefix(event_type_prefix), None)


def apply_projections(
    event: EventRecord,
    snapshot: Mapping[str, Any],
    registry: Mapping[str, ProjectionUpdater] | None = None,
) -> dict[str, Any]:
    """Apply matching projection updaters, marking the snapshot stale on failure."""
    updated = dict(snapshot)
    for prefix, updater in _matching_updaters(event.type, registry or DEFAULT_REGISTRY):
        try:
            updated = updater.update_snapshot(event, updated)
        except Exception as exc:  # noqa: BLE001 - projection failure must not lose the event.
            return _mark_stale(updated, event, prefix, exc)
    return updated


def load_projection_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Load the durable projection snapshot from ``aggregates``."""
    row = connection.execute(
        "SELECT snapshot FROM aggregates WHERE aggregate_id = ?",
        (PROJECTION_AGGREGATE_ID,),
    ).fetchone()
    if row is None:
        return {}
    try:
        parsed = json.loads(str(row["snapshot"]))
    except (KeyError, TypeError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def persist_projection_snapshot(
    connection: sqlite3.Connection,
    snapshot: Mapping[str, Any],
    *,
    last_sequence: int,
    updated_at: str,
) -> None:
    """Persist ``snapshot`` into the aggregate cache row."""
    connection.execute(
        """
        INSERT INTO aggregates(aggregate_id, type, last_sequence, snapshot, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(aggregate_id) DO UPDATE SET
            type = excluded.type,
            last_sequence = excluded.last_sequence,
            snapshot = excluded.snapshot,
            updated_at = excluded.updated_at
        """,
        (
            PROJECTION_AGGREGATE_ID,
            PROJECTION_AGGREGATE_TYPE,
            last_sequence,
            _canonical_json(snapshot),
            updated_at,
        ),
    )


def project_event_in_transaction(
    connection: sqlite3.Connection,
    event: EventRecord,
    *,
    inserted: bool,
) -> None:
    """Apply projections for one newly inserted event without raising."""
    if not inserted or event.aggregate_id == PROJECTION_AGGREGATE_ID:
        return
    snapshot = load_projection_snapshot(connection)
    updated = apply_projections(event, snapshot)
    persist_projection_snapshot(
        connection,
        updated,
        last_sequence=int(snapshot.get("_projection_sequence", 0)) + 1,
        updated_at=event.created_at,
    )


def rebuild_projection(
    connection: sqlite3.Connection,
    *,
    from_event_id: str | None = None,
    registry: Mapping[str, ProjectionUpdater] | None = None,
) -> tuple[dict[str, Any], int, int]:
    """Replay events into a fresh snapshot and replace the cache atomically.

    Returns ``(snapshot, events_replayed, duration_ms)``.
    """
    start = time.monotonic()
    events = _read_rebuild_events(connection, from_event_id=from_event_id)
    snapshot: dict[str, Any] = {}
    for event in events:
        if event.aggregate_id == PROJECTION_AGGREGATE_ID:
            continue
        snapshot = apply_projections(event, snapshot, registry=registry)
    duration_ms = int((time.monotonic() - start) * 1000)
    updated_at = events[-1].created_at if events else iso8601_utc_now()
    persist_projection_snapshot(
        connection,
        snapshot,
        last_sequence=len(events),
        updated_at=updated_at,
    )
    return snapshot, len(events), duration_ms


def _read_rebuild_events(
    connection: sqlite3.Connection,
    *,
    from_event_id: str | None,
) -> list[EventRecord]:
    if from_event_id is None:
        rows = connection.execute(
            """
            SELECT event_id, aggregate_id, sequence, type, payload, created_at
            FROM events
            ORDER BY rowid ASC
            """
        ).fetchall()
    else:
        marker = connection.execute(
            "SELECT rowid FROM events WHERE event_id = ?",
            (from_event_id,),
        ).fetchone()
        if marker is None:
            msg = f"event not found: {from_event_id}"
            raise ValueError(msg)
        rows = connection.execute(
            """
            SELECT event_id, aggregate_id, sequence, type, payload, created_at
            FROM events
            WHERE rowid >= ?
            ORDER BY rowid ASC
            """,
            (int(marker["rowid"]),),
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


def _matching_updaters(
    event_type: str,
    registry: Mapping[str, ProjectionUpdater],
) -> list[tuple[str, ProjectionUpdater]]:
    return [
        (prefix, updater)
        for prefix, updater in sorted(registry.items())
        if event_type.startswith(_normalize_prefix(prefix))
    ]


def _normalize_prefix(prefix: str) -> str:
    return prefix[:-1] if prefix.endswith("*") else prefix


def _payload_object(event: EventRecord) -> dict[str, Any]:
    payload = event.payload_data
    return dict(payload) if isinstance(payload, dict) else {}


def _copy_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    parsed = json.loads(_canonical_json(snapshot))
    return dict(parsed) if isinstance(parsed, dict) else {}


def _mark_fresh(snapshot: dict[str, Any], event: EventRecord) -> dict[str, Any]:
    snapshot["stale"] = False
    snapshot.pop("stale_reason", None)
    snapshot.pop("stale_since_event_id", None)
    snapshot["last_event_id"] = event.event_id
    snapshot["last_event_type"] = event.type
    return snapshot


def _mark_stale(
    snapshot: dict[str, Any],
    event: EventRecord,
    prefix: str,
    exc: Exception,
) -> dict[str, Any]:
    updated = dict(snapshot)
    updated["stale"] = True
    updated["stale_reason"] = f"{prefix}: {type(exc).__name__}: {exc}"
    updated["stale_since_event_id"] = event.event_id
    updated["last_event_id"] = event.event_id
    updated["last_event_type"] = event.type
    return updated


def _nested_count_map(snapshot: Mapping[str, Any], key: str) -> dict[str, int]:
    raw = snapshot.get(key)
    if not isinstance(raw, dict):
        return {}
    return {str(item_key): int(item_value) for item_key, item_value in raw.items()}


def _criteria_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("criteria_summary")
    summary = dict(raw) if isinstance(raw, dict) else {}
    raw_by_criterion = summary.get("by_criterion")
    by_criterion = dict(raw_by_criterion) if isinstance(raw_by_criterion, dict) else {}
    return {
        "passed": int(summary.get("passed", 0)),
        "failed": int(summary.get("failed", 0)),
        "unverified": int(summary.get("unverified", 0)),
        "by_criterion": {str(key): str(value) for key, value in by_criterion.items()},
    }


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
