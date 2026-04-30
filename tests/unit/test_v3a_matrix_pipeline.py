"""Unit tests for the MatrixPipeline seam."""

from __future__ import annotations

from mobius.v3a.matrix.pipeline import deserialize, diff, score, serialize
from mobius.v3a.scoring.engine import ScoreInputs, ScoreResult
from mobius.workflow.seed import SeedSpec


def _trivial_spec(matrix: dict[str, list[str]] | None = None) -> SeedSpec:
    return SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="trivial fixture goal",
        constraints=["constraint a"],
        success_criteria=["criterion a"],
        context="",
        matrix=matrix or {},
    )


def _score(value: int) -> ScoreResult:
    return ScoreResult(
        score_out_of_10=value,
        score_rationale=f"score {value}",
        score_breakdown={"mechanical": {"a": value}, "llm": {"b": 0}},
        score_recommendations=[f"keep {value}"],
    )


def test_serialize_deserialize_round_trip_preserves_matrix_scores() -> None:
    scores = {
        "platform=ios,python=3.12": _score(8),
        "platform=android,python=3.12": _score(7),
    }

    assert deserialize(serialize(scores)) == scores


def test_score_uses_supplied_artifacts_adapter_for_declared_cells() -> None:
    spec = _trivial_spec({"platform": ["ios", "android"]})
    artifacts = {
        "platform=ios": ScoreInputs(spec=spec, run_id="matrix-cell:platform=ios"),
        "platform=android": ScoreInputs(
            spec=spec,
            run_id="matrix-cell:platform=android",
        ),
    }

    scores = score(spec, artifacts=artifacts)

    assert list(scores) == ["platform=ios", "platform=android"]
    assert all(isinstance(result, ScoreResult) for result in scores.values())


def test_diff_surfaces_tolerated_regressions_through_pipeline() -> None:
    report = diff(
        baseline={"platform=ios": _score(8)},
        current={"platform=ios": _score(7)},
        tolerance=1,
    )

    assert report.verdict == "pass"
    assert [delta.cell_key for delta in report.tolerated_regressions] == ["platform=ios"]
