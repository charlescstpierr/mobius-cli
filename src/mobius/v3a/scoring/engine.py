"""Phase 4 v3a score engine: 7 mechanical bits + 3 LLM bits."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mobius.v3a.scoring.llm_judge import LLMJudgeInputs, judge_llm_dimensions
from mobius.v3a.scoring.mechanical import (
    MechanicalInputs,
    VerificationResult,
    compute_mechanical_score,
)
from mobius.v3a.scoring.rationale import build_score_rationale
from mobius.v3a.scoring.recommend import build_score_recommendations
from mobius.workflow.seed import SeedSpec, load_seed_spec


class EventSink(Protocol):
    """Event-store surface needed by the scoring engine."""

    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> Any:
        """Append one event to the backing store."""


@dataclass(frozen=True)
class ScoreInputs:
    """Inputs used to compute the complete v3a score."""

    spec: SeedSpec | Path
    run_id: str
    branch_coverage_percent: float = 100.0
    mypy_errors: int = 0
    verification_results: tuple[VerificationResult, ...] = ()
    ambiguity_score: float | None = None
    ruff_errors: int = 0
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreResult:
    """Stable JSON-ready v3a score result."""

    score_out_of_10: int
    score_rationale: str
    score_breakdown: dict[str, dict[str, int] | dict[str, int | str | float]]
    score_recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible score payload."""
        return {
            "score_out_of_10": self.score_out_of_10,
            "score_rationale": self.score_rationale,
            "score_breakdown": {
                "mechanical": dict(self.score_breakdown["mechanical"]),
                "llm": dict(self.score_breakdown["llm"]),
            },
            "score_recommendations": list(self.score_recommendations),
        }

    def write_json(self, path: Path) -> None:
        """Write the score payload to ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        path.write_text(payload, encoding="utf-8")


def compute_score(inputs: ScoreInputs, *, event_sink: EventSink | None = None) -> ScoreResult:
    """Compute and optionally emit all Phase 4 scoring events."""
    spec = load_seed_spec(inputs.spec) if isinstance(inputs.spec, Path) else inputs.spec
    mechanical = compute_mechanical_score(
        MechanicalInputs(
            spec=spec,
            branch_coverage_percent=inputs.branch_coverage_percent,
            mypy_errors=inputs.mypy_errors,
            verification_results=inputs.verification_results,
            ambiguity_score=inputs.ambiguity_score,
            ruff_errors=inputs.ruff_errors,
        )
    )
    if event_sink is not None:
        event_sink.append_event(
            inputs.run_id,
            "scoring.mechanical_computed",
            {"breakdown": mechanical.breakdown, "details": mechanical.details},
        )
        event_sink.append_event(
            inputs.run_id,
            "scoring.llm_judgment_started",
            {"dimensions": ["goal_alignment", "code_quality", "test_quality"]},
        )
    llm_result = judge_llm_dimensions(
        LLMJudgeInputs(
            spec=spec,
            mechanical_breakdown=mechanical.breakdown,
            artifacts=inputs.artifacts,
        )
    )
    llm_scores = llm_result.dimension_scores
    if event_sink is not None:
        event_sink.append_event(
            inputs.run_id,
            "scoring.llm_judgment_completed",
            {
                "breakdown": dict(llm_result.breakdown),
                "calls": {key: list(value) for key, value in llm_result.calls.items()},
            },
        )
    total = int(mechanical.total + sum(llm_scores.values()))
    result = ScoreResult(
        score_out_of_10=total,
        score_rationale=build_score_rationale(
            mechanical=mechanical.breakdown,
            llm=llm_scores,
        ),
        score_breakdown={
            "mechanical": dict(mechanical.breakdown),
            "llm": dict(llm_result.breakdown),
        },
        score_recommendations=build_score_recommendations(
            mechanical=mechanical.breakdown,
            llm=llm_scores,
        ),
    )
    if event_sink is not None:
        event_sink.append_event(inputs.run_id, "scoring.final_computed", result.to_dict())
    return result
