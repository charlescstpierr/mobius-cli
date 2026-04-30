"""Smoke tests for the MatrixScorer.

Per PRD F10 and CONTEXT.md, ``MatrixScorer`` applies ``compute_score()``
cell by cell of the *Product matrix* of a *Spec*. The scorer itself is
stateless and never fetches artifacts — the caller (CLI or workflow CI)
provides ``MatrixArtifacts`` keyed by ``cell_key``.

These tests verify external behavior only (how many cells, in what order,
keyed how) — never internal helpers. The exhaustive scoring math lives in
``tests/unit/test_v3a_scoring*`` and is not re-tested here.
"""

from __future__ import annotations

import pytest

from mobius.v3a.matrix.scorer import MatrixArtifacts, score_matrix
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


def _inputs_for(spec: SeedSpec, cell_key: str) -> ScoreInputs:
    return ScoreInputs(spec=spec, run_id=f"matrix-cell:{cell_key}")


def test_score_matrix_returns_one_score_per_cell_in_declaration_order() -> None:
    spec = _trivial_spec({"platform": ["ios", "android"], "python": ["3.12", "3.13"]})
    artifacts: MatrixArtifacts = {
        "platform=ios,python=3.12": _inputs_for(spec, "platform=ios,python=3.12"),
        "platform=ios,python=3.13": _inputs_for(spec, "platform=ios,python=3.13"),
        "platform=android,python=3.12": _inputs_for(spec, "platform=android,python=3.12"),
        "platform=android,python=3.13": _inputs_for(spec, "platform=android,python=3.13"),
    }

    scores = score_matrix(spec, artifacts)

    assert list(scores.keys()) == [
        "platform=ios,python=3.12",
        "platform=ios,python=3.13",
        "platform=android,python=3.12",
        "platform=android,python=3.13",
    ]
    for result in scores.values():
        assert isinstance(result, ScoreResult)
        assert 0 <= result.score_out_of_10 <= 10


def test_score_matrix_returns_empty_mapping_when_spec_has_no_matrix() -> None:
    spec = _trivial_spec(matrix={})

    scores = score_matrix(spec, artifacts={})

    assert scores == {}


def test_score_matrix_raises_when_artifacts_are_missing_for_a_declared_cell() -> None:
    spec = _trivial_spec({"platform": ["ios", "android"]})

    with pytest.raises(KeyError, match="platform=android"):
        score_matrix(
            spec,
            artifacts={"platform=ios": _inputs_for(spec, "platform=ios")},
        )
