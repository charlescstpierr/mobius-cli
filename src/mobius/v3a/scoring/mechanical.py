"""Deterministic mechanical dimensions for the v3a /10 score."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mobius.workflow.seed import SeedSpec, load_seed_spec

MECHANICAL_DIMENSIONS: tuple[str, ...] = (
    "spec_completeness",
    "coverage",
    "mypy",
    "verifications_pass",
    "ambiguity",
    "no_timeouts",
    "ruff_clean",
)

VerificationStatus = Literal["PASS", "FAIL", "TIMEOUT", "N/A"]


@dataclass(frozen=True)
class VerificationResult:
    """Result for one verification command observed by the runner or CI."""

    status: VerificationStatus


@dataclass(frozen=True)
class MechanicalInputs:
    """Inputs required to compute deterministic mechanical score bits."""

    spec: SeedSpec | Path
    branch_coverage_percent: float = 100.0
    mypy_errors: int = 0
    verification_results: tuple[VerificationResult, ...] = ()
    ambiguity_score: float | None = None
    ruff_errors: int = 0


@dataclass(frozen=True)
class MechanicalScore:
    """Binary mechanical score plus stable diagnostic details."""

    breakdown: dict[str, int]
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Return the whole-number mechanical subtotal."""
        return sum(self.breakdown.values())

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        return {"breakdown": dict(self.breakdown), "details": dict(self.details)}


def compute_mechanical_score(inputs: MechanicalInputs) -> MechanicalScore:
    """Compute the seven deterministic binary dimensions."""
    spec = load_seed_spec(inputs.spec) if isinstance(inputs.spec, Path) else inputs.spec
    spec_ratio = _spec_completeness_ratio(spec)
    ambiguity = (
        _compute_ambiguity_score(spec)
        if inputs.ambiguity_score is None
        else float(inputs.ambiguity_score)
    )
    pass_rate = _verification_pass_rate(inputs.verification_results)
    timeout_rate = _verification_timeout_rate(inputs.verification_results)
    breakdown = {
        "spec_completeness": int(spec_ratio >= 0.95),
        "coverage": int(inputs.branch_coverage_percent >= 95.0),
        "mypy": int(inputs.mypy_errors == 0),
        "verifications_pass": int(pass_rate is None or pass_rate == 1.0),
        "ambiguity": int(ambiguity <= 0.2),
        "no_timeouts": int(timeout_rate < 0.05),
        "ruff_clean": int(inputs.ruff_errors == 0),
    }
    return MechanicalScore(
        breakdown=breakdown,
        details={
            "criteria_count": len(spec.success_criteria),
            "spec_completeness_ratio": round(spec_ratio, 6),
            "branch_coverage_percent": inputs.branch_coverage_percent,
            "mypy_errors": inputs.mypy_errors,
            "verification_pass_rate": pass_rate,
            "ambiguity_score": ambiguity,
            "verification_timeout_rate": timeout_rate,
            "ruff_errors": inputs.ruff_errors,
        },
    )


def _spec_completeness_ratio(spec: SeedSpec) -> float:
    if not spec.success_criteria:
        return 0.0
    covered = 0
    for index, criterion in enumerate(spec.success_criteria, start=1):
        refs = _criterion_references(index, criterion)
        if any(_command_matches(command, refs) for command in spec.verification_commands):
            covered += 1
    return covered / len(spec.success_criteria)


def _verification_pass_rate(results: tuple[VerificationResult, ...]) -> float | None:
    executable = [result for result in results if result.status != "N/A"]
    if not executable:
        return None
    passed = sum(1 for result in executable if result.status == "PASS")
    return passed / len(executable)


def _verification_timeout_rate(results: tuple[VerificationResult, ...]) -> float:
    executable = [result for result in results if result.status != "N/A"]
    if not executable:
        return 0.0
    timed_out = sum(1 for result in executable if result.status == "TIMEOUT")
    return timed_out / len(executable)


def _compute_ambiguity_score(spec: SeedSpec) -> float:
    from mobius.workflow.interview import InterviewFixture, compute_ambiguity_score

    fixture = InterviewFixture(
        project_type=spec.project_type,
        goal=spec.goal,
        constraints=list(spec.constraints),
        success=list(spec.success_criteria),
        context=spec.context,
        template=spec.template or "blank",
    )
    return compute_ambiguity_score(fixture).score


def _criterion_references(index: int, criterion: str) -> set[str]:
    return {str(index), f"criterion-{index}", f"success-{index}", f"sc-{index}", criterion}


def _command_matches(command: dict[str, Any], references: set[str]) -> bool:
    raw_ref = str(command.get("criterion_ref", "")).strip()
    if raw_ref in references:
        return True
    command_text = " ".join(str(value) for value in command.values()).lower()
    return any(reference.lower() in command_text for reference in references if len(reference) > 8)
