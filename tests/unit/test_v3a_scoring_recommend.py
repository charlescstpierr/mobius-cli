from __future__ import annotations

from mobius.v3a.scoring.engine import ScoreInputs, compute_score
from mobius.v3a.scoring.llm_judge import LLM_DIMENSIONS
from mobius.v3a.scoring.mechanical import MECHANICAL_DIMENSIONS, VerificationResult
from mobius.v3a.scoring.recommend import (
    build_score_recommendations,
    recommendation_for,
)


def test_each_zero_point_dimension_produces_actionable_recommendation() -> None:
    all_dimensions = (*MECHANICAL_DIMENSIONS, *LLM_DIMENSIONS)

    for dim_id in all_dimensions:
        recommendation = recommendation_for(dim_id, 0)

        assert recommendation
        assert dim_id in recommendation
        assert "0/1" in recommendation
        assert any(
            verb in recommendation.lower()
            for verb in ("add", "raise", "run", "fix", "clarify", "reduce", "revise")
        )


def test_score_recommendations_empty_when_score_is_ten(scoring_spec) -> None:
    result = compute_score(
        ScoreInputs(
            spec=scoring_spec,
            run_id="perfect-score",
            verification_results=(VerificationResult("PASS"),),
            ambiguity_score=0.1,
        )
    )

    assert result.score_out_of_10 == 10
    assert result.score_recommendations == []
    assert result.to_dict()["score_recommendations"] == []


def test_score_recommendations_include_one_entry_per_lost_point() -> None:
    recommendations = build_score_recommendations(
        mechanical={
            "spec_completeness": 0,
            "coverage": 0,
            "mypy": 1,
            "verifications_pass": 1,
            "ambiguity": 1,
            "no_timeouts": 1,
            "ruff_clean": 1,
        },
        llm={"goal_alignment": 1, "code_quality": 0, "test_quality": 1},
    )

    assert len(recommendations) == 3
    assert any("spec_completeness" in item for item in recommendations)
    assert any("coverage" in item for item in recommendations)
    assert any("code_quality" in item for item in recommendations)
