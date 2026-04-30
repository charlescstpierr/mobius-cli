"""Projection for v3a phase-router events."""

from __future__ import annotations

from typing import Any

from mobius.persistence.event_store import EventRecord
from mobius.v3a.projections.store import DEFAULT_V3A_PROJECTION_STORE, ProjectionStore


class PhaseRouterProjection:
    """Track the latest v3a phase-router state in the projection cache."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return an updated snapshot for a phase-router event."""
        snapshot = dict(current_snapshot)
        phase_state = dict(snapshot.get("v3a_phase", {}))
        payload = event.payload_data if isinstance(event.payload_data, dict) else {}
        phase_state["last_event_type"] = event.type
        phase_state["last_event_at"] = event.created_at
        if event.type == "phase.entered":
            phase_state["current_phase"] = payload.get("phase")
            phase_state["current_phase_index"] = payload.get("phase_index")
        elif event.type == "phase.completed":
            phase_state["last_completed_phase"] = payload.get("phase")
            phase_state["last_completed_phase_index"] = payload.get("phase_index")
            phase_state["last_summary"] = payload.get("summary")
        elif event.type == "phase.proposed_next":
            phase_state["next_phase"] = payload.get("next_phase")
            phase_state["next_command"] = payload.get("next_command")
        snapshot["v3a_phase"] = phase_state
        return snapshot


_PHASE_PROJECTION = PhaseRouterProjection()


def register_phase_projection(
    store: ProjectionStore = DEFAULT_V3A_PROJECTION_STORE,
) -> PhaseRouterProjection:
    """Register the phase-router projection adapter with ``store``."""
    store.register("phase.", _PHASE_PROJECTION)
    return _PHASE_PROJECTION


register_phase_projection()
