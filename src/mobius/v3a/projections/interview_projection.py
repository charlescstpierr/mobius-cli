"""Projection for v3a interview events."""

from __future__ import annotations

from typing import Any

from mobius.persistence.event_store import EventRecord
from mobius.persistence.projections import register_projection


class InterviewProjection:
    """Track the latest v3a interview progress in the projection cache."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return an updated snapshot for an interview event."""
        snapshot = dict(current_snapshot)
        interview = dict(snapshot.get("v3a_interview", {}))
        payload = event.payload_data if isinstance(event.payload_data, dict) else {}
        interview["last_event_type"] = event.type
        interview["last_event_at"] = event.created_at
        if event.type == "interview.transcript_appended":
            interview["turn"] = payload.get("turn")
            interview["transcript"] = payload.get("transcript")
        elif event.type in {"interview.lemma_check_passed", "interview.lemma_check_blocked"}:
            interview["last_lemma_check"] = event.type.removeprefix("interview.lemma_check_")
        snapshot["v3a_interview"] = interview
        return snapshot


register_projection("interview.", InterviewProjection())
