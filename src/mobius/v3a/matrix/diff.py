"""MatrixDiff — pure deep module that compares two MatrixScores.

Per PRD F10 and CONTEXT.md, a *Quality score* is computed per cell of the
*Product matrix*. This module compares a baseline (last main run) to a
candidate (current PR) and emits a verdict that blocks the CI guardrail
when any cell regresses.

The module is pure: no I/O, no subprocess, no LLM, no GitHub coupling.
All inputs are passed in; all outputs are returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from mobius.v3a.scoring.engine import ScoreResult


@dataclass(frozen=True)
class CellDelta:
    """A per-cell score delta between baseline and candidate."""

    cell_key: str
    baseline_score: int
    candidate_score: int
    delta: int


@dataclass(frozen=True)
class MatrixDiffReport:
    """Verdict of comparing one MatrixScores baseline against a candidate."""

    regressions: tuple[CellDelta, ...]
    improvements: tuple[CellDelta, ...]
    unchanged: tuple[str, ...]
    new_cells: tuple[str, ...]
    dropped_cells: tuple[str, ...]
    verdict: Literal["pass", "fail"]


def diff(
    baseline: Mapping[str, ScoreResult],
    candidate: Mapping[str, ScoreResult],
    *,
    tolerance: int = 0,
) -> MatrixDiffReport:
    """Return a MatrixDiffReport comparing ``candidate`` against ``baseline``."""
    unchanged: list[str] = []
    regressions: list[CellDelta] = []
    improvements: list[CellDelta] = []
    dropped_cells: list[str] = []
    for cell_key, baseline_result in baseline.items():
        if cell_key not in candidate:
            dropped_cells.append(cell_key)
            continue
        candidate_result = candidate[cell_key]
        baseline_value = baseline_result.score_out_of_10
        candidate_value = candidate_result.score_out_of_10
        delta = candidate_value - baseline_value
        cell_delta = CellDelta(
            cell_key=cell_key,
            baseline_score=baseline_value,
            candidate_score=candidate_value,
            delta=delta,
        )
        if delta == 0:
            unchanged.append(cell_key)
        elif delta < -tolerance:
            regressions.append(cell_delta)
        elif delta > 0:
            improvements.append(cell_delta)
        # else: delta < 0 but absorbed by tolerance — currently dropped from
        # the report. If the CLI grows a need to surface "soft warnings", add
        # a `tolerated_regressions` field rather than silently restoring them.
    new_cells = [cell_key for cell_key in candidate if cell_key not in baseline]
    verdict: Literal["pass", "fail"] = "fail" if regressions else "pass"
    return MatrixDiffReport(
        regressions=tuple(regressions),
        improvements=tuple(improvements),
        unchanged=tuple(unchanged),
        new_cells=tuple(new_cells),
        dropped_cells=tuple(dropped_cells),
        verdict=verdict,
    )
