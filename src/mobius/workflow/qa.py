"""Deterministic offline QA heuristics for Mobius runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventRecord, EventStore
from mobius.workflow.seed import (
    SeedSpec,
    SeedSpecValidationError,
    SpecGrade,
    assign_bronze_grade,
    load_seed_spec,
)

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
    grade: str | None = None


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
    grade = _assign_static_grade(events, session)
    if grade is not None:
        with EventStore(event_store_path) as store:
            store.append_event(run_id, "spec.grade_assigned", grade.to_event_payload())
    return QAReport(
        run_id=run_id,
        mode="offline",
        state=state,
        summary=QASummary(total=len(results), failed=failed),
        results=results,
        grade=grade.grade if grade is not None else None,
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


def assign_silver_grade(spec: SeedSpec) -> SpecGrade:
    """Assign the highest static grade available to a parsed spec.

    Silver requires all Bronze checks plus at least one verification command
    linked to every success criterion, at least one non-goal, and an owner.
    """
    bronze = assign_bronze_grade(spec)
    linked_criteria = _success_criteria_with_commands(spec)
    details = {
        **bronze.details,
        "all_success_criteria_linked": linked_criteria == len(spec.success_criteria),
        "non_goals_present": len(spec.non_goals) >= 1,
        "owner_present": _owner_present(spec.owner),
    }
    criteria_met = sum(1 for passed in details.values() if passed)
    grade = "silver" if criteria_met == len(details) else bronze.grade
    return SpecGrade(
        grade=grade,
        criteria_met=criteria_met,
        criteria_total=len(details),
        details=details,
    )


def _assign_static_grade(events: list[EventRecord], session: Any) -> SpecGrade | None:
    spec_path = _spec_path_from_session(session) or _spec_path_from_events(events)
    if spec_path is None:
        return None
    try:
        spec = load_seed_spec(spec_path)
    except (OSError, SeedSpecValidationError):
        return None
    return assign_silver_grade(spec)


def _spec_path_from_session(session: Any) -> Path | None:
    metadata = _decode_json_object(str(session["metadata"]))
    raw_path = metadata.get("spec_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    return Path(raw_path).expanduser()


def _spec_path_from_events(events: list[EventRecord]) -> Path | None:
    for event in reversed(events):
        if event.type != "run.started":
            continue
        payload = _decode_json_object(event.payload)
        raw_path = payload.get("spec_path")
        if isinstance(raw_path, str) and raw_path:
            return Path(raw_path).expanduser()
    return None


def _success_criteria_with_commands(spec: SeedSpec) -> int:
    linked = 0
    for index, criterion in enumerate(spec.success_criteria, start=1):
        references = _criterion_reference_keys(criterion, index)
        if any(
            _command_matches_criterion(command, references)
            for command in spec.verification_commands
        ):
            linked += 1
    return linked


def _command_matches_criterion(command: dict[str, Any], references: set[str]) -> bool:
    raw_ref = command.get("criterion_ref")
    if raw_ref is None:
        raw_ref = command.get("criterion_refs")
    if raw_ref is None:
        raw_ref = command.get("criteria")
    if isinstance(raw_ref, list):
        return any(_normalize_ref(item) in references for item in raw_ref)
    return _normalize_ref(raw_ref) in references


def _criterion_reference_keys(criterion: str, index: int) -> set[str]:
    stripped = criterion.strip()
    keys = {
        str(index),
        f"criterion-{index}",
        f"criterion_{index}",
        f"C{index}",
        f"c{index}",
        stripped,
    }
    first_token = stripped.split(maxsplit=1)[0] if stripped else ""
    if first_token:
        keys.add(first_token.rstrip(":.-—"))
    return {_normalize_ref(key) for key in keys if key}


def _normalize_ref(value: object) -> str:
    return " ".join(str(value).strip().split()).lower()


def _owner_present(owner: str | list[str]) -> bool:
    if isinstance(owner, list):
        return any(item.strip() for item in owner)
    return bool(owner.strip())


def _event_detail(event_type: str, event_types: set[str]) -> str:
    return "present" if event_type in event_types else f"missing {event_type}"
