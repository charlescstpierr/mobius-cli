from __future__ import annotations

import json
from typing import Any

from mobius.persistence.event_store import EventRecord
from mobius.persistence.projections import apply_projections
from mobius.v3a.projections.audit_projection import register_audit_projection
from mobius.v3a.projections.interview_projection import register_interview_projection
from mobius.v3a.projections.phase_projection import register_phase_projection
from mobius.v3a.projections.scoring_projection import register_scoring_projection
from mobius.v3a.projections.store import InMemoryProjectionStore


def test_v3a_projections_register_with_in_memory_store() -> None:
    store = InMemoryProjectionStore()

    register_audit_projection(store)
    register_phase_projection(store)
    register_scoring_projection(store)
    register_interview_projection(store)

    assert sorted(store.registry) == [
        "human.",
        "interview.",
        "phase.",
        "scoring.",
        "spec.maturity_overridden",
    ]


def test_audit_phase_scoring_and_interview_projections_use_in_memory_store() -> None:
    store = InMemoryProjectionStore()
    register_audit_projection(store)
    register_phase_projection(store)
    register_scoring_projection(store)
    register_interview_projection(store)

    snapshot: dict[str, Any] = {}
    for index, (event_type, payload) in enumerate(
        [
            (
                "human.maturity_override_requested",
                {"reason": "ship a spike", "maturity_score": 0.42},
            ),
            (
                "phase.completed",
                {"phase": "seed", "phase_index": 2, "summary": "wrote spec.yaml"},
            ),
            (
                "scoring.final_computed",
                {
                    "score_out_of_10": 8,
                    "score_rationale": "clear",
                    "score_breakdown": {"mechanical": 4, "llm": 4},
                },
            ),
            (
                "interview.transcript_appended",
                {"turn": 3, "transcript": "## Turn 3\n"},
            ),
        ],
        start=1,
    ):
        snapshot = apply_projections(
            _event(index, event_type, payload),
            snapshot,
            registry=store.as_registry(),
        )

    assert snapshot["v3a_audit"]["last_reason"] == "ship a spike"
    assert snapshot["v3a_phase"]["last_completed_phase"] == "seed"
    assert snapshot["v3a_scoring"]["score_out_of_10"] == 8
    assert snapshot["v3a_interview"]["turn"] == 3


def _event(index: int, event_type: str, payload: dict[str, Any]) -> EventRecord:
    return EventRecord(
        event_id=f"event-{index}",
        aggregate_id="build-test",
        sequence=index,
        type=event_type,
        payload=json.dumps(payload),
        created_at=f"2026-04-29T00:00:0{index}.000000Z",
    )
