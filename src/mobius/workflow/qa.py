"""Deterministic offline QA heuristics for Mobius runs."""

from __future__ import annotations

import json
from enum import StrEnum
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
from mobius.workflow.verify import ProofRecord, run_verification

_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})
_FAILURE_EVENT_TYPES = frozenset({"run.failed", "run.crashed", "run.cancelled", "run.interrupted"})


class Verdict(StrEnum):
    """Ternary QA verdict with worst-wins ordering."""

    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


class QASummary(BaseModel):
    """Aggregate QA verdict counts."""

    model_config = ConfigDict(extra="forbid")

    total: int
    passed: int
    failed: int
    unverified: int
    global_verdict: Verdict


class QAResult(BaseModel):
    """One deterministic QA check result."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    verdict: Verdict
    detail: str

    @property
    def passed(self) -> bool:
        """Return whether this result is a passing verdict."""
        return self.verdict == Verdict.PASS


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
            verdict=_bool_verdict(state in _TERMINAL_STATES),
            detail=f"state={state}",
        ),
        QAResult(
            id="run_completed_successfully",
            label="Run completed successfully",
            verdict=_bool_verdict(state == "completed"),
            detail=f"state={state}",
        ),
        QAResult(
            id="event_stream_started",
            label="Event stream contains run.started",
            verdict=_bool_verdict("run.started" in event_types),
            detail=_event_detail("run.started", event_types),
        ),
        QAResult(
            id="event_stream_completed",
            label="Event stream contains run.completed",
            verdict=_bool_verdict("run.completed" in event_types),
            detail=_event_detail("run.completed", event_types),
        ),
        QAResult(
            id="spec_has_success_criteria",
            label="Seed spec contains success criteria",
            verdict=_bool_verdict(spec_criteria_count > 0),
            detail=f"success_criteria={spec_criteria_count}",
        ),
        QAResult(
            id="no_failure_events",
            label="Event stream contains no failure events",
            verdict=_bool_verdict(not failure_events),
            detail=("none" if not failure_events else f"failure_events={','.join(failure_events)}"),
        ),
    ]
    criterion_results = _evaluate_success_criteria(
        event_store_path,
        run_id,
        events,
        session,
    )
    results.extend(criterion_results)
    summary = _summarize_results(results, criterion_results)
    grade = _assign_static_grade(events, session)
    if grade is not None:
        with EventStore(event_store_path) as store:
            store.append_event(run_id, "spec.grade_assigned", grade.to_event_payload())
    return QAReport(
        run_id=run_id,
        mode="offline",
        state=state,
        summary=summary,
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


def _evaluate_success_criteria(
    event_store_path: Path,
    run_id: str,
    events: list[EventRecord],
    session: Any,
) -> list[QAResult]:
    spec_path = _spec_path_from_session(session) or _spec_path_from_events(events)
    if spec_path is None:
        return []
    try:
        spec = load_seed_spec(spec_path)
    except (OSError, SeedSpecValidationError):
        return []

    config = _load_verification_config(event_store_path.parent)
    results: list[QAResult] = []
    with EventStore(event_store_path) as store:
        for index, criterion in enumerate(spec.success_criteria, start=1):
            references = _criterion_reference_keys(criterion, index)
            command_specs = [
                command
                for command in spec.verification_commands
                if _command_matches_criterion(command, references)
            ]
            if not command_specs:
                results.append(_unverified_criterion_result(index, criterion))
                continue
            proofs: list[ProofRecord] = []
            for command_spec in command_specs:
                try:
                    proof = run_verification(command_spec, spec_path.parent, config)
                except ValueError as exc:
                    results.append(_malformed_command_result(index, criterion, exc))
                    proofs = []
                    break
                store.append_event(
                    run_id,
                    "qa.verification_executed",
                    proof.executed_event_payload(),
                )
                store.append_event(run_id, "qa.proof_collected", proof.proof_event_payload())
                proofs.append(proof)
            if proofs:
                results.append(_qa_result_from_proofs(index, criterion, proofs))
    return results


def _load_verification_config(mobius_home: Path) -> dict[str, Any]:
    config_path = mobius_home / "config.json"
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _qa_result_from_proofs(index: int, criterion: str, proofs: list[ProofRecord]) -> QAResult:
    verdict = _worst_verdict(
        Verdict.PASS if proof.exit_code == 0 and not proof.timed_out else Verdict.FAIL
        for proof in proofs
    )
    proof_details = []
    for proof in proofs:
        timeout_detail = ", timed_out=true" if proof.timed_out else ""
        truncated_detail = ", truncated=true" if proof.truncated else ""
        proof_details.append(
            f"{proof.command!r}: exit_code={proof.exit_code}, duration_ms={proof.duration_ms}"
            f"{timeout_detail}{truncated_detail}"
        )
    return QAResult(
        id=f"criterion_{index}",
        label=f"Criterion {index}: {criterion}",
        verdict=verdict,
        detail="; ".join(proof_details),
    )


def _unverified_criterion_result(index: int, criterion: str) -> QAResult:
    return QAResult(
        id=f"criterion_{index}",
        label=f"Criterion {index}: {criterion}",
        verdict=Verdict.UNVERIFIED,
        detail="no verification_command linked to this criterion",
    )


def _malformed_command_result(index: int, criterion: str, exc: ValueError) -> QAResult:
    return QAResult(
        id=f"criterion_{index}",
        label=f"Criterion {index}: {criterion}",
        verdict=Verdict.FAIL,
        detail=f"malformed verification_command: {exc}",
    )


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


def _bool_verdict(passed: bool) -> Verdict:
    return Verdict.PASS if passed else Verdict.FAIL


def _summarize_results(results: list[QAResult], criterion_results: list[QAResult]) -> QASummary:
    counted_results = criterion_results if criterion_results else results
    passed = sum(1 for result in counted_results if result.verdict == Verdict.PASS)
    failed = sum(1 for result in counted_results if result.verdict == Verdict.FAIL)
    unverified = sum(1 for result in counted_results if result.verdict == Verdict.UNVERIFIED)
    return QASummary(
        total=len(counted_results),
        passed=passed,
        failed=failed,
        unverified=unverified,
        global_verdict=_worst_verdict(result.verdict for result in results),
    )


def _worst_verdict(verdicts: Any) -> Verdict:
    worst = Verdict.PASS
    for verdict in verdicts:
        if verdict == Verdict.FAIL:
            return Verdict.FAIL
        if verdict == Verdict.UNVERIFIED:
            worst = Verdict.UNVERIFIED
    return worst
