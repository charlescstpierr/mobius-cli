"""Ambiguity trend helpers backed by the v2 interview scorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mobius.workflow.interview import AmbiguityScore, InterviewFixture


@dataclass(frozen=True)
class AmbiguityTrend:
    """Current ambiguity score and delta from the previous turn."""

    score: AmbiguityScore
    delta: float


def compute_trend(fixture: InterviewFixture, previous_score: float | None) -> AmbiguityTrend:
    """Compute ambiguity using the verbatim v2 ``compute_ambiguity_score`` symbol."""
    from mobius.workflow.interview import compute_ambiguity_score

    score = compute_ambiguity_score(fixture)
    delta = 0.0 if previous_score is None else round(score.score - previous_score, 3)
    return AmbiguityTrend(score=score, delta=delta)


def convergence_conditions_met(fixture: InterviewFixture) -> bool:
    """Return whether v3a's score and component thresholds are satisfied."""
    from mobius.workflow.interview import compute_ambiguity_score

    score = compute_ambiguity_score(fixture)
    max_component = max(score.components.values(), default=1.0)
    return score.score < 0.2 and max_component < 0.4
