"""Rationale rendering for v3a binary score output."""

from __future__ import annotations

from mobius.v3a.scoring.llm_judge import LLM_DIMENSIONS
from mobius.v3a.scoring.mechanical import MECHANICAL_DIMENSIONS


def build_score_rationale(
    *,
    mechanical: dict[str, int],
    llm: dict[str, int],
) -> str:
    """Return a ≥3 sentence rationale that mentions ≥6 dimensions."""
    passed_mechanical = [dim for dim in MECHANICAL_DIMENSIONS if mechanical.get(dim) == 1]
    failed_mechanical = [dim for dim in MECHANICAL_DIMENSIONS if mechanical.get(dim) == 0]
    goal = _passed_or_failed("goal_alignment", llm)
    code = _passed_or_failed("code_quality", llm)
    tests = _passed_or_failed("test_quality", llm)
    mechanical_sentence = (
        "Mechanical dimensions "
        f"{', '.join(MECHANICAL_DIMENSIONS)} produced {sum(mechanical.values())}/7, "
        f"with passed dimensions {', '.join(passed_mechanical) or 'none'} and "
        f"lost dimensions {', '.join(failed_mechanical) or 'none'}."
    )
    llm_quality_sentence = (
        "[LLM] goal_alignment "
        f"{goal}, code_quality {code}, and test_quality {tests} after median-of-three "
        "temperature-0.0 judgments."
    )
    closing_sentence = (
        "[LLM] The combined rationale maps spec_completeness, coverage, mypy, "
        "verifications_pass, ambiguity, no_timeouts, ruff_clean, goal_alignment, "
        "code_quality, and test_quality to the final whole-number score."
    )
    return " ".join([mechanical_sentence, llm_quality_sentence, closing_sentence])


def mentioned_dimension_count(rationale: str) -> int:
    """Count how many scoring dimensions are named in ``rationale``."""
    dimensions = (*MECHANICAL_DIMENSIONS, *LLM_DIMENSIONS)
    return sum(1 for dimension in dimensions if dimension in rationale)


def _passed_or_failed(dimension: str, llm: dict[str, int]) -> str:
    return "passed 1/1" if llm.get(dimension) == 1 else "failed 0/1"
