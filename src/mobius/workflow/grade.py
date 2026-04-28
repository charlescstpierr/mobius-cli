"""Projection-backed Gold grade evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventStore
from mobius.persistence.projections import load_projection_snapshot
from mobius.workflow.handoff import render_handoff
from mobius.workflow.seed import SeedSpec


class GoldGradeReport(BaseModel):
    """Result of evaluating the runtime Gold grade."""

    model_config = ConfigDict(extra="forbid")

    grade: str
    criteria_met: int
    criteria_total: int
    details: dict[str, bool]

    def event_payload(self) -> dict[str, Any]:
        """Return a ``spec.grade_assigned`` event payload."""
        return {
            "grade": self.grade,
            "criteria_met": self.criteria_met,
            "criteria_total": self.criteria_total,
            "details": dict(self.details),
        }


def evaluate_gold_grade(
    event_store_path: Path,
    *,
    agent: str = "claude",
    emit: bool = True,
) -> GoldGradeReport:
    """Evaluate Gold using only the durable projection snapshot.

    The evaluator never replays events and never runs verification commands.
    It loads the cached projection row, checks the projected QA/run/proof
    facts, renders a dry-run handoff prompt from projected spec metadata, and
    optionally appends the resulting ``spec.grade_assigned`` event.
    """
    snapshot = _load_snapshot(event_store_path)
    report = evaluate_gold_snapshot(snapshot, agent=agent)
    if emit:
        with EventStore(event_store_path) as store:
            store.append_event(
                "mobius.grade",
                "spec.grade_assigned",
                report.event_payload(),
            )
    return report


def evaluate_gold_snapshot(snapshot: dict[str, Any], *, agent: str = "claude") -> GoldGradeReport:
    """Evaluate the Gold grade from an already-loaded projection snapshot."""
    details = {
        "silver_grade_present": _silver_grade_present(snapshot),
        "all_success_criteria_passed": _all_success_criteria_passed(snapshot),
        "run_succeeded": _run_succeeded(snapshot),
        "handoff_dry_run_complete": _handoff_dry_run_complete(snapshot, agent=agent),
        "proof_per_criterion": _proof_per_criterion(snapshot),
    }
    criteria_met = sum(1 for passed in details.values() if passed)
    grade = "gold" if criteria_met == len(details) else _fallback_grade(snapshot)
    return GoldGradeReport(
        grade=grade,
        criteria_met=criteria_met,
        criteria_total=len(details),
        details=details,
    )


def _load_snapshot(event_store_path: Path) -> dict[str, Any]:
    if not event_store_path.exists():
        return {}
    with EventStore(event_store_path, read_only=True) as store:
        return load_projection_snapshot(store.connection)


def _silver_grade_present(snapshot: dict[str, Any]) -> bool:
    grade = _dict(snapshot.get("last_grade")).get("grade")
    return grade in {"silver", "gold"}


def _all_success_criteria_passed(snapshot: dict[str, Any]) -> bool:
    criteria = _criteria(snapshot)
    if not criteria:
        return False
    if any(str(criterion.get("verdict", "")).lower() != "pass" for criterion in criteria):
        return False
    summary = _dict(snapshot.get("criteria_summary"))
    if summary:
        return int(summary.get("failed", 0)) == 0 and int(summary.get("unverified", 0)) == 0
    return True


def _run_succeeded(snapshot: dict[str, Any]) -> bool:
    status = str(_dict(snapshot.get("latest_run")).get("status", "")).lower()
    return status in {"succeeded", "completed"}


def _handoff_dry_run_complete(snapshot: dict[str, Any], *, agent: str) -> bool:
    spec = _seed_spec_from_projection(snapshot)
    if spec is None:
        return False
    try:
        prompt = render_handoff(spec, agent=agent).prompt
    except ValueError:
        return False
    required_markers = ("<GOAL>", "<CRITERIA>", "<COMMANDS>", "<RISKS>")
    return all(marker in prompt for marker in required_markers) and spec.goal in prompt


def _proof_per_criterion(snapshot: dict[str, Any]) -> bool:
    criteria = _criteria(snapshot)
    if not criteria:
        return False
    proofs = _proofs_by_normalized_ref(snapshot)
    for index, criterion in enumerate(criteria, start=1):
        refs = _criterion_reference_keys(
            str(criterion.get("label", "")),
            index,
            str(criterion.get("id", "")),
        )
        if not any(proofs.get(ref, 0) >= 1 for ref in refs):
            return False
    return True


def _fallback_grade(snapshot: dict[str, Any]) -> str:
    grade = str(_dict(snapshot.get("last_grade")).get("grade", "")).strip().lower()
    return grade if grade in {"bronze", "silver"} else "bronze"


def _seed_spec_from_projection(snapshot: dict[str, Any]) -> SeedSpec | None:
    spec = _dict(snapshot.get("current_spec"))
    goal = str(spec.get("goal", "")).strip()
    criteria = _text_list(spec.get("success_criteria"))
    if not goal or not criteria:
        return None
    return SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal=goal,
        constraints=_text_list(spec.get("constraints")) or ["Projection-backed grade evaluation."],
        success_criteria=criteria,
        context="",
        non_goals=_text_list(spec.get("non_goals")),
        verification_commands=_mapping_list(spec.get("verification_commands")),
        risks=_mapping_list(spec.get("risks")),
        artifacts=_mapping_list(spec.get("artifacts")),
        owner=spec.get("owner", ""),
        agent_instructions=_agent_instructions(spec.get("agent_instructions")),
        spec_version=2,
    )


def _criteria(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("criteria")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _proofs_by_normalized_ref(snapshot: dict[str, Any]) -> dict[str, int]:
    raw = snapshot.get("proofs_by_criterion")
    if not isinstance(raw, dict):
        return {}
    return {_normalize_ref(key): int(value) for key, value in raw.items()}


def _criterion_reference_keys(label: str, index: int, criterion_id: str) -> set[str]:
    stripped = label.strip()
    keys = {
        str(index),
        f"criterion-{index}",
        f"criterion_{index}",
        f"C{index}",
        f"c{index}",
        stripped,
        criterion_id,
    }
    first_token = stripped.split(maxsplit=1)[0] if stripped else ""
    if first_token:
        keys.add(first_token.rstrip(":.-—"))
    return {_normalize_ref(key) for key in keys if key}


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _agent_instructions(value: object) -> str | dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return str(value).strip() if value is not None else ""


def _normalize_ref(value: object) -> str:
    return " ".join(str(value).strip().split()).lower()
