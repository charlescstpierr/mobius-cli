"""Deterministic lost-point recommendations for the v3a score."""

from __future__ import annotations

from collections.abc import Mapping

from mobius.v3a.scoring.llm_judge import LLM_DIMENSIONS
from mobius.v3a.scoring.mechanical import MECHANICAL_DIMENSIONS

DIMENSION_RECOMMENDATIONS: dict[str, str] = {
    "spec_completeness": (
        "spec_completeness 0/1: add or link a verification_command for at "
        "least 95% of success criteria so each requirement has an executable check."
    ),
    "coverage": (
        "coverage 0/1: raise branch coverage to at least 95% by adding tests "
        "for untested branches before recomputing the score."
    ),
    "mypy": (
        "mypy 0/1: run `uv run mypy --strict src/mobius/`, fix every reported "
        "type error, and rerun scoring after the command exits cleanly."
    ),
    "verifications_pass": (
        "verifications_pass 0/1: rerun the declared verification commands, fix "
        "all failing checks, and keep only PASS or N/A results."
    ),
    "ambiguity": (
        "ambiguity 0/1: clarify the goal, constraints, and success criteria "
        "until the v2 ambiguity score is at or below 0.2."
    ),
    "no_timeouts": (
        "no_timeouts 0/1: reduce flaky or slow verification commands so fewer "
        "than 5% of executable checks time out."
    ),
    "ruff_clean": (
        "ruff_clean 0/1: run `uv run ruff check src/ tests/`, fix every lint "
        "diagnostic, and rerun scoring once ruff is clean."
    ),
    "goal_alignment": (
        "goal_alignment 0/1: revise the implementation or spec so delivered "
        "behavior directly satisfies the stated user goal and success criteria."
    ),
    "code_quality": (
        "code_quality 0/1: fix unclear code by improving names and structure, "
        "then remove avoidable duplication before asking the judge to rescore."
    ),
    "test_quality": (
        "test_quality 0/1: add meaningful happy-path, edge-case, and failure-path "
        "tests that prove the success criteria instead of only checking smoke paths."
    ),
}


def recommendation_for(dim_id: str, current_value: int) -> str:
    """Return an actionable recommendation for a lost scoring point."""
    if current_value == 1:
        return ""
    try:
        return DIMENSION_RECOMMENDATIONS[dim_id]
    except KeyError as exc:
        msg = f"unknown scoring dimension: {dim_id}"
        raise ValueError(msg) from exc


def build_score_recommendations(
    *,
    mechanical: Mapping[str, int],
    llm: Mapping[str, int],
) -> list[str]:
    """Return one deterministic recommendation for each lost scoring point."""
    recommendations: list[str] = []
    for dim_id in (*MECHANICAL_DIMENSIONS, *LLM_DIMENSIONS):
        scores = mechanical if dim_id in MECHANICAL_DIMENSIONS else llm
        recommendation = recommendation_for(dim_id, int(scores.get(dim_id, 0)))
        if recommendation:
            recommendations.append(recommendation)
    return recommendations
