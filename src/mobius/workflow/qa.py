"""Deterministic offline QA heuristics for Mobius runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventRecord, EventStore

_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})
_FAILURE_EVENT_TYPES = frozenset({"run.failed", "run.crashed", "run.cancelled", "run.interrupted"})


class QASummary(BaseModel):
    """Aggregate QA verdict counts."""

    model_config = ConfigDict(extra="forbid")

    total: int
    failed: int


class QAResult(BaseModel):
    """One deterministic QA check result."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    passed: bool
    detail: str


class QAReport(BaseModel):
    """Structured output for ``mobius qa``."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: str
    state: str
    summary: QASummary
    results: list[QAResult]


def evaluate_run_qa(event_store_path: Path, run_id: str) -> QAReport | None:
    """Evaluate a run with local, deterministic heuristics.

    The offline judge intentionally does not call an LLM. It checks the durable
    event-store facts that indicate a run reached a successful terminal state
    and that its seed spec contains acceptance criteria to judge against.
    """
    with EventStore(event_store_path) as store:
        session = _read_session(store, run_id)
        if session is None:
            return None
        events = store.read_events(run_id)

    state = str(session["status"])
    spec_criteria_count = _load_success_criteria_count(events)
    event_types = {event.type for event in events}
    failure_events = sorted(event_types & _FAILURE_EVENT_TYPES)

    results = [
        QAResult(
            id="session_terminal",
            label="Session reached a terminal state",
            passed=state in _TERMINAL_STATES,
            detail=f"state={state}",
        ),
        QAResult(
            id="run_completed_successfully",
            label="Run completed successfully",
            passed=state == "completed",
            detail=f"state={state}",
        ),
        QAResult(
            id="event_stream_started",
            label="Event stream contains run.started",
            passed="run.started" in event_types,
            detail=_event_detail("run.started", event_types),
        ),
        QAResult(
            id="event_stream_completed",
            label="Event stream contains run.completed",
            passed="run.completed" in event_types,
            detail=_event_detail("run.completed", event_types),
        ),
        QAResult(
            id="spec_has_success_criteria",
            label="Seed spec contains success criteria",
            passed=spec_criteria_count > 0,
            detail=f"success_criteria={spec_criteria_count}",
        ),
        QAResult(
            id="no_failure_events",
            label="Event stream contains no failure events",
            passed=not failure_events,
            detail=("none" if not failure_events else f"failure_events={','.join(failure_events)}"),
        ),
    ]
    failed = sum(1 for result in results if not result.passed)
    return QAReport(
        run_id=run_id,
        mode="offline",
        state=state,
        summary=QASummary(total=len(results), failed=failed),
        results=results,
    )


def _read_session(store: EventStore, run_id: str) -> Any | None:
    return store.connection.execute(
        """
        SELECT session_id, status, metadata
        FROM sessions
        WHERE session_id = ?
        """,
        (run_id,),
    ).fetchone()


def _decode_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _load_success_criteria_count(events: list[EventRecord]) -> int:
    for event in reversed(events):
        if event.type != "run.completed":
            continue
        payload = _decode_json_object(event.payload)
        count = payload.get("success_criteria_count")
        if isinstance(count, int):
            return count
    return 0


def _event_detail(event_type: str, event_types: set[str]) -> str:
    return "present" if event_type in event_types else f"missing {event_type}"
