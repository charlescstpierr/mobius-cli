"""Unit tests for the MatrixDiff deep module.

Per PRD F10 and CONTEXT.md: a *Quality score* is computed per cell of the
*Product matrix*; this module compares a baseline (last main run) to a
candidate (current PR) and emits a verdict that blocks the CI guardrail
when any cell regresses.

These tests verify external behavior only (verdict, listed cells, deltas) —
never internal helpers.
"""

from __future__ import annotations

from mobius.v3a.matrix.diff import CellDelta, MatrixDiffReport, diff
from mobius.v3a.scoring.engine import ScoreResult


def _score(value: int) -> ScoreResult:
    """Build a minimal ScoreResult fixture with the given Quality score."""
    return ScoreResult(
        score_out_of_10=value,
        score_rationale="",
        score_breakdown={"mechanical": {}, "llm": {}},
    )


def test_diff_of_two_empty_matrices_is_pass_with_empty_lists() -> None:
    report = diff(baseline={}, candidate={})

    assert isinstance(report, MatrixDiffReport)
    assert report.verdict == "pass"
    assert report.regressions == ()
    assert report.tolerated_regressions == ()
    assert report.improvements == ()
    assert report.unchanged == ()
    assert report.new_cells == ()
    assert report.dropped_cells == ()


def test_diff_with_one_unchanged_cell_lists_it_as_unchanged() -> None:
    cell = "platform=ios,python=3.12"
    s = _score(8)

    report = diff(baseline={cell: s}, candidate={cell: s})

    assert report.verdict == "pass"
    assert report.unchanged == (cell,)
    assert report.regressions == ()
    assert report.tolerated_regressions == ()
    assert report.improvements == ()
    assert report.new_cells == ()
    assert report.dropped_cells == ()


def test_diff_with_one_regressed_cell_lists_it_and_fails() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(baseline={cell: _score(8)}, candidate={cell: _score(6)})

    assert report.verdict == "fail"
    assert len(report.regressions) == 1
    delta = report.regressions[0]
    assert isinstance(delta, CellDelta)
    assert delta.cell_key == cell
    assert delta.baseline_score == 8
    assert delta.candidate_score == 6
    assert delta.delta == -2
    assert report.unchanged == ()
    assert report.tolerated_regressions == ()
    assert report.improvements == ()


def test_diff_with_dropped_cell_lists_it_as_dropped_not_regression() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(baseline={cell: _score(8)}, candidate={})

    assert report.verdict == "pass"
    assert report.dropped_cells == (cell,)
    assert report.regressions == ()
    assert report.tolerated_regressions == ()
    assert report.unchanged == ()


def test_diff_with_new_cell_lists_it_as_new_not_regression() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(baseline={}, candidate={cell: _score(8)})

    assert report.verdict == "pass"
    assert report.new_cells == (cell,)
    assert report.regressions == ()
    assert report.tolerated_regressions == ()
    assert report.unchanged == ()


def test_diff_with_one_improved_cell_lists_it_and_passes() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(baseline={cell: _score(6)}, candidate={cell: _score(8)})

    assert report.verdict == "pass"
    assert len(report.improvements) == 1
    delta = report.improvements[0]
    assert delta.cell_key == cell
    assert delta.baseline_score == 6
    assert delta.candidate_score == 8
    assert delta.delta == 2
    assert report.regressions == ()
    assert report.tolerated_regressions == ()
    assert report.unchanged == ()


def test_tolerance_of_one_absorbs_a_regression_of_exactly_one_point() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(
        baseline={cell: _score(8)},
        candidate={cell: _score(7)},
        tolerance=1,
    )

    assert report.verdict == "pass"
    assert report.regressions == ()
    assert len(report.tolerated_regressions) == 1
    tolerated = report.tolerated_regressions[0]
    assert tolerated.cell_key == cell
    assert tolerated.baseline_score == 8
    assert tolerated.candidate_score == 7
    assert tolerated.delta == -1


def test_tolerance_of_one_does_not_absorb_a_regression_of_two_points() -> None:
    cell = "platform=ios,python=3.12"

    report = diff(
        baseline={cell: _score(8)},
        candidate={cell: _score(6)},
        tolerance=1,
    )

    assert report.verdict == "fail"
    assert len(report.regressions) == 1
    assert report.regressions[0].delta == -2
    assert report.tolerated_regressions == ()


def test_diff_partitions_mixed_regression_improvement_and_unchanged_correctly() -> None:
    regressed = "platform=ios,python=3.12"
    improved = "platform=android,python=3.12"
    same = "platform=ios,python=3.13"

    baseline = {regressed: _score(8), improved: _score(5), same: _score(7)}
    candidate = {regressed: _score(6), improved: _score(9), same: _score(7)}

    report = diff(baseline=baseline, candidate=candidate)

    assert report.verdict == "fail"
    assert len(report.regressions) == 1
    assert report.regressions[0].cell_key == regressed
    assert report.tolerated_regressions == ()
    assert len(report.improvements) == 1
    assert report.improvements[0].cell_key == improved
    assert report.unchanged == (same,)
    assert report.new_cells == ()
    assert report.dropped_cells == ()
