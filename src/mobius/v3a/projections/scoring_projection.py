"""Projection for v3a scoring events."""

from __future__ import annotations

from typing import Any

from mobius.persistence.event_store import EventRecord
from mobius.v3a.projections.store import DEFAULT_V3A_PROJECTION_STORE, ProjectionStore


class ScoringProjection:
    """Track the latest v3a score state in the projection cache."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return an updated snapshot for a scoring event."""
        snapshot = dict(current_snapshot)
        scoring = dict(snapshot.get("v3a_scoring", {}))
        payload = event.payload_data if isinstance(event.payload_data, dict) else {}
        scoring["last_event_type"] = event.type
        scoring["last_event_at"] = event.created_at
        if event.type == "scoring.mechanical_computed":
            scoring["mechanical"] = payload.get("breakdown")
        elif event.type == "scoring.llm_judgment_started":
            scoring["llm_status"] = "started"
            scoring["llm_dimensions"] = payload.get("dimensions")
        elif event.type == "scoring.llm_judgment_completed":
            scoring["llm_status"] = "completed"
            scoring["llm"] = payload.get("breakdown")
        elif event.type == "scoring.final_computed":
            scoring["score_out_of_10"] = payload.get("score_out_of_10")
            scoring["score_rationale"] = payload.get("score_rationale")
            scoring["score_breakdown"] = payload.get("score_breakdown")
        snapshot["v3a_scoring"] = scoring
        return snapshot


_SCORING_PROJECTION = ScoringProjection()


def register_scoring_projection(
    store: ProjectionStore = DEFAULT_V3A_PROJECTION_STORE,
) -> ScoringProjection:
    """Register the scoring projection adapter with ``store``."""
    store.register("scoring.", _SCORING_PROJECTION)
    return _SCORING_PROJECTION


register_scoring_projection()
