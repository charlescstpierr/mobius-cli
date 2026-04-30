from __future__ import annotations

import json
from contextlib import nullcontext
from io import StringIO
from typing import Any

from mobius.v3a.phase_router.router import PhaseResult, PhaseRouter
from mobius.v3a.phase_router.transitions import PhaseDefinition


class FakeEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: object,
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> None:
        _ = aggregate_id, sequence, event_id
        assert isinstance(payload, dict)
        self.events.append((event_type, dict(payload)))


def test_phase_router_dispatches_events_and_agent_payloads_through_fake_sink() -> None:
    sink = FakeEventSink()
    output = StringIO()
    router = PhaseRouter(run_id="build-test", event_sink=sink, mode="agent", output=output)

    payloads = router.run(
        {
            "interview": _handler("interview done"),
            "seed": _handler("seed done"),
            "maturity": _handler("maturity done"),
            "scoring": _handler("scoring done", converged=True),
        }
    )

    assert [event_type for event_type, _payload in sink.events] == [
        "phase.entered",
        "phase.completed",
        "phase.proposed_next",
        "phase.entered",
        "phase.completed",
        "phase.proposed_next",
        "phase.entered",
        "phase.completed",
        "phase.proposed_next",
        "phase.entered",
        "phase.completed",
        "phase.proposed_next",
    ]
    assert sink.events[0][1] == {"phase": "interview", "phase_index": 1}
    assert sink.events[-2][1]["summary"] == "scoring done"
    assert [payload.phase_done for payload in payloads] == [
        "interview",
        "seed",
        "maturity",
        "scoring",
    ]
    assert json.loads(output.getvalue().splitlines()[0])["phase_done"] == "interview"


def test_phase_router_uses_injected_renderer_adapter() -> None:
    sink = FakeEventSink()
    output = StringIO()
    live_instances: list[object] = []

    def live_factory() -> object:
        live = nullcontext()
        live_instances.append(live)
        return live

    router = PhaseRouter(
        run_id="build-test",
        event_sink=sink,
        mode="interactive",
        output=output,
        live_factory=live_factory,
    )

    router.run({"scoring": _handler("scoring only")}, start_phase_key="scoring")

    assert len(live_instances) == 1
    assert "[Phase 4/4 complete — Scoring + Delivery]" in output.getvalue()
    assert sink.events[0] == ("phase.entered", {"phase": "scoring", "phase_index": 4})


def _handler(summary: str, *, converged: bool = False) -> Any:
    def handle(phase: PhaseDefinition) -> PhaseResult:
        return PhaseResult(
            summary=summary,
            payload={"phase_key": phase.key},
            converged_proposed=converged,
        )

    return handle
