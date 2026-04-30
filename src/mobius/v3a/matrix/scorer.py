"""MatrixScorer — apply ``compute_score()`` per cell of a Spec's matrix.

Per PRD F10 and CONTEXT.md, the *Quality score* of a *Run* is computed
per cell of the *Product matrix* declared in the *Spec*. This module
loops over those cells in declaration order and delegates the actual
scoring math to ``mobius.v3a.scoring.engine.compute_score`` — F10 is a
layer above the scoring engine, never a fork of it.

The scorer is stateless and pure: it does no I/O, no LLM calls of its
own (``compute_score`` may call its mock-judge, but that's its concern),
and never goes looking for artifacts. The caller passes a
``MatrixArtifacts`` mapping ``cell_key -> ScoreInputs`` covering every
declared cell.
"""

from __future__ import annotations

from collections.abc import Mapping

from mobius.v3a.matrix.pipeline import score as score_pipeline
from mobius.v3a.scoring.engine import ScoreInputs, ScoreResult
from mobius.workflow.seed import SeedSpec

MatrixArtifacts = Mapping[str, ScoreInputs]
"""Caller-provided mapping of cell_key to scoring inputs for that cell."""

MatrixScores = Mapping[str, ScoreResult]
"""Per-cell scoring outputs returned by ``score_matrix``."""


def score_matrix(spec: SeedSpec, artifacts: MatrixArtifacts) -> dict[str, ScoreResult]:
    """Return one ``ScoreResult`` per declared cell of ``spec.matrix``.

    Cells are iterated in the axis order declared by ``spec.matrix``
    (mirrored from the Spec YAML/JSON), so two invocations on equivalent
    inputs produce the same key sequence — a property the canonical JSON
    output of ``mobius v3a matrix score`` relies on.

    Raises ``KeyError`` if ``artifacts`` is missing an entry for any
    declared cell. Extra entries in ``artifacts`` are ignored — that lets
    a CI workflow build a superset once and reuse it across slices.
    """
    return score_pipeline(spec, artifacts=artifacts)
