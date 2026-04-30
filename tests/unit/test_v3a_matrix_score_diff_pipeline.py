"""Integration test piping ``mobius v3a matrix score`` into ``matrix diff``.

Per PRD F10, the canonical JSON written by the score CLI is the exact
input format consumed by the diff CLI. Running both back-to-back on a
trivial fixture must therefore yield a coherent verdict — proof that the
two slices interoperate without a hand-edited file in the middle.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mobius.cli.main import app


def test_score_then_diff_against_self_yields_pass_verdict(
    cli_runner: CliRunner, spec_factory, tmp_path: Path
) -> None:
    spec = spec_factory(
        tmp_path / "spec.yaml",
        matrix_block="matrix:\n  platform:\n    - ios\n    - android\n",
    )
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"

    score_baseline = cli_runner.invoke(
        app, ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(baseline)]
    )
    score_candidate = cli_runner.invoke(
        app, ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(candidate)]
    )

    assert score_baseline.exit_code == 0, score_baseline.stdout
    assert score_candidate.exit_code == 0, score_candidate.stdout

    diff_result = cli_runner.invoke(
        app,
        [
            "v3a",
            "matrix",
            "diff",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
        ],
    )

    assert diff_result.exit_code == 0, diff_result.stdout
    assert "no regression" in diff_result.stdout.lower()
