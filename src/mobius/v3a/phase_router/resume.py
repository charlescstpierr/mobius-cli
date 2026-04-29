"""Resume support for ``mobius build --resume``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mobius.v3a.phase_router.transitions import PHASE_BY_KEY

if TYPE_CHECKING:
    from mobius.persistence.event_store import EventStore


@dataclass(frozen=True)
class ResumePoint:
    """The phase-router position recovered from the project event store."""

    run_id: str
    completed_phase: str
    next_phase: str
    artifacts: dict[str, Any]


class ResumeUsageError(ValueError):
    """Raised when ``--resume`` cannot identify a next phase."""


def latest_resume_point(store: EventStore) -> ResumePoint:
    """Return the next phase after the latest ``phase.completed`` event.

    The query deliberately uses v2's ``EventStore`` connection instead of a
    direct ``sqlite3`` import so v3a keeps lazy-import/cold-start discipline.
    """
    row = store.connection.execute(
        """
        SELECT event_id, aggregate_id, sequence, type, payload, created_at
        FROM events
        WHERE type = 'phase.completed'
        ORDER BY created_at DESC, sequence DESC, event_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        msg = "mobius build --resume requires at least one phase.completed event"
        raise ResumeUsageError(msg)

    payload = json.loads(str(row["payload"]))
    if not isinstance(payload, dict):
        msg = "latest phase.completed event has an invalid payload"
        raise ResumeUsageError(msg)
    completed_phase = str(payload.get("phase", ""))
    phase = PHASE_BY_KEY.get(completed_phase)
    if phase is None:
        msg = f"latest phase.completed event has unknown phase: {completed_phase!r}"
        raise ResumeUsageError(msg)
    if phase.next_key is None:
        msg = "latest phase.completed event is terminal; no next phase remains"
        raise ResumeUsageError(msg)
    return ResumePoint(
        run_id=str(row["aggregate_id"]),
        completed_phase=completed_phase,
        next_phase=phase.next_key,
        artifacts=json.loads(json.dumps(payload)),
    )
