"""Audit projection for v3a human override events."""

from __future__ import annotations

from typing import Any

from mobius.persistence.event_store import EventRecord
from mobius.v3a.projections.store import DEFAULT_V3A_PROJECTION_STORE, ProjectionStore


class AuditProjection:
    """Track v3a audit events such as maturity overrides."""

    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return an updated snapshot for an audit event."""
        snapshot = dict(current_snapshot)
        audit = dict(snapshot.get("v3a_audit", {}))
        events = list(audit.get("events", []))
        payload = event.payload_data if isinstance(event.payload_data, dict) else {}
        events.append(
            {
                "event_type": event.type,
                "aggregate_id": event.aggregate_id,
                "created_at": event.created_at,
                "reason": payload.get("reason"),
                "maturity_score": payload.get("maturity_score"),
            }
        )
        audit["events"] = events[-50:]
        audit["last_event_type"] = event.type
        audit["last_reason"] = payload.get("reason")
        audit["last_maturity_score"] = payload.get("maturity_score")
        snapshot["v3a_audit"] = audit
        return snapshot


_AUDIT_PROJECTION = AuditProjection()


def register_audit_projection(
    store: ProjectionStore = DEFAULT_V3A_PROJECTION_STORE,
) -> AuditProjection:
    """Register audit projection adapters with ``store`` and return the updater."""
    store.register("human.", _AUDIT_PROJECTION)
    store.register("spec.maturity_overridden", _AUDIT_PROJECTION)
    return _AUDIT_PROJECTION


register_audit_projection()
