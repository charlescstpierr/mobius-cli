from __future__ import annotations

from mobius.v3a.scoring.engine import ScoreInputs, compute_score
from mobius.v3a.scoring.mechanical import (
    MECHANICAL_DIMENSIONS,
    MechanicalInputs,
    VerificationResult,
    compute_mechanical_score,
)


def test_score_is_integer_with_7_mechanical_and_3_llm_binary_dimensions(scoring_spec) -> None:
    result = compute_score(
        ScoreInputs(
            spec=scoring_spec,
            run_id="run-score",
            verification_results=(VerificationResult("PASS"),),
            ambiguity_score=0.1,
        )
    )

    assert isinstance(result.score_out_of_10, int)
    assert 0 <= result.score_out_of_10 <= 10
    assert set(result.score_breakdown["mechanical"]) == set(MECHANICAL_DIMENSIONS)
    assert len(result.score_breakdown["mechanical"]) == 7
    assert {"goal_alignment", "code_quality", "test_quality"}.issubset(
        result.score_breakdown["llm"]
    )
    assert all(value in {0, 1} for value in result.score_breakdown["mechanical"].values())
    assert all(
        result.score_breakdown["llm"][key] in {0, 1}
        for key in ("goal_alignment", "code_quality", "test_quality")
    )


def test_mechanical_dimensions_are_bit_identical_for_fixed_inputs(scoring_spec) -> None:
    inputs = MechanicalInputs(
        spec=scoring_spec,
        branch_coverage_percent=95.0,
        mypy_errors=0,
        verification_results=(
            VerificationResult("PASS"),
            VerificationResult("PASS"),
            VerificationResult("N/A"),
        ),
        ambiguity_score=0.2,
        ruff_errors=0,
    )

    first = compute_mechanical_score(inputs).to_dict()
    second = compute_mechanical_score(inputs).to_dict()

    assert first == second


def test_mechanical_lost_points_cover_threshold_edges(scoring_spec) -> None:
    inputs = MechanicalInputs(
        spec=scoring_spec,
        branch_coverage_percent=94.9,
        mypy_errors=1,
        verification_results=(
            VerificationResult("PASS"),
            VerificationResult("FAIL"),
            VerificationResult("TIMEOUT"),
        ),
        ambiguity_score=0.201,
        ruff_errors=1,
    )

    score = compute_mechanical_score(inputs)

    assert score.breakdown == {
        "spec_completeness": 1,
        "coverage": 0,
        "mypy": 0,
        "verifications_pass": 0,
        "ambiguity": 0,
        "no_timeouts": 0,
        "ruff_clean": 0,
    }
    assert score.details["verification_pass_rate"] == 1 / 3
    assert score.details["verification_timeout_rate"] == 1 / 3
