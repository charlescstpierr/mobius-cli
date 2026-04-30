"""MatrixPipeline seam for scoring, diffing, and score serialization.

The pipeline owns the Matrix score interface used by the CLI: callers ask it
to score a Spec, serialize the resulting MatrixScores, deserialize previously
serialized MatrixScores, or diff two MatrixScores. That keeps ScoreResult's
field-level JSON shape local to this module instead of spreading it across CLI
adapters.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from itertools import product
from typing import Any

from mobius.v3a.matrix.diff import MatrixDiffReport
from mobius.v3a.matrix.diff import diff as matrix_diff
from mobius.v3a.scoring.engine import ScoreInputs, ScoreResult, compute_score
from mobius.workflow.seed import SeedSpec

MATRIX_SCHEMA_VERSION = 1
MatrixScores = dict[str, ScoreResult]
MatrixArtifacts = Mapping[str, ScoreInputs]


class MatrixSerializationError(ValueError):
    """Raised when serialized MatrixScores do not match the pipeline schema."""


def score(spec: SeedSpec, artifacts: MatrixArtifacts | None = None) -> MatrixScores:
    """Return one score per declared matrix cell.

    When ``artifacts`` is omitted, the pipeline builds the default
    ``ScoreInputs`` adapter used by the CLI. Tests and future workflows can
    provide an alternate adapter mapping to verify the seam without touching
    the CLI.
    """
    scores: MatrixScores = {}
    for combination in _iter_matrix_cells(spec.matrix):
        key = _cell_key_from_combination(combination)
        if artifacts is None:
            score_inputs = ScoreInputs(
                spec=spec,
                run_id=f"matrix-cell:{key}",
            )
        else:
            if key not in artifacts:
                msg = (
                    f"missing ScoreInputs for matrix cell {key!r}; "
                    "the caller must provide artifacts for every declared cell"
                )
                raise KeyError(msg)
            score_inputs = artifacts[key]
        scores[key] = compute_score(score_inputs)
    return scores


def _cell_key_from_combination(combination: Sequence[tuple[str, str]]) -> str:
    """Return a stable cell key preserving the Spec's declared axis order."""
    return ",".join(f"{axis}={value}" for axis, value in combination)


def _iter_matrix_cells(
    matrix: Mapping[str, Sequence[str]],
) -> Iterator[tuple[tuple[str, str], ...]]:
    """Yield every matrix cell in declared axis/value order."""
    if not matrix:
        return
    axis_names = list(matrix.keys())
    axis_values = [list(matrix[name]) for name in axis_names]
    for combination in product(*axis_values):
        yield tuple(zip(axis_names, combination, strict=True))


def diff(
    baseline: Mapping[str, ScoreResult],
    current: Mapping[str, ScoreResult],
    *,
    tolerance: int = 0,
) -> MatrixDiffReport:
    """Return a diff report for two MatrixScores mappings."""
    return matrix_diff(baseline=baseline, candidate=current, tolerance=tolerance)


def serialize(scores: Mapping[str, ScoreResult]) -> dict[str, Any]:
    """Return the canonical JSON-ready MatrixScores payload."""
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "scores": {key: result.to_dict() for key, result in scores.items()},
    }


def deserialize(payload: Mapping[str, Any]) -> MatrixScores:
    """Validate and hydrate a canonical MatrixScores payload."""
    schema_version = payload.get("schema_version")
    if schema_version != MATRIX_SCHEMA_VERSION:
        msg = f"Unsupported schema_version {schema_version!r}; expected {MATRIX_SCHEMA_VERSION}."
        raise MatrixSerializationError(msg)

    scores_raw = payload.get("scores", {})
    if not isinstance(scores_raw, Mapping):
        raise MatrixSerializationError("Field 'scores' must be an object.")

    scores: MatrixScores = {}
    for cell_key, score_data in scores_raw.items():
        if not isinstance(cell_key, str):
            raise MatrixSerializationError("Score cell keys must be strings.")
        if not isinstance(score_data, Mapping):
            raise MatrixSerializationError(f"Score for cell {cell_key!r} must be an object.")
        try:
            scores[cell_key] = ScoreResult(
                score_out_of_10=int(score_data["score_out_of_10"]),
                score_rationale=str(score_data.get("score_rationale", "")),
                score_breakdown=dict(
                    score_data.get("score_breakdown", {"mechanical": {}, "llm": {}})
                ),
                score_recommendations=list(score_data.get("score_recommendations", [])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            msg = f"Invalid score payload for cell {cell_key!r}: {exc}"
            raise MatrixSerializationError(msg) from exc
    return scores
