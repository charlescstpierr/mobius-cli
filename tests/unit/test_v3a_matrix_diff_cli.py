"""CLI-level tests for ``mobius v3a matrix diff``.

These tests invoke the public Typer app and assert exit codes plus stdout
shape — no mocks, no internal helpers. Per CONTEXT.md, the verdict is
``pass`` / ``fail`` and the CLI mirrors that in its exit code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mobius.cli.main import app


def _baseline_payload(scores: dict[str, int]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "scores": {
            cell_key: {
                "score_out_of_10": value,
                "score_rationale": "",
                "score_breakdown": {"mechanical": {}, "llm": {}},
                "score_recommendations": [],
            }
            for cell_key, value in scores.items()
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_diff_cli_exits_zero_when_no_regression(
    cli_runner: CliRunner, tmp_path: Path
) -> None:
    cell = "platform=ios,python=3.12"
    baseline = _write_json(
        tmp_path / "baseline.json", _baseline_payload({cell: 8})
    )
    candidate = _write_json(
        tmp_path / "candidate.json", _baseline_payload({cell: 8})
    )

    result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "diff", "--baseline", str(baseline), "--candidate", str(candidate)],
    )

    assert result.exit_code == 0, result.stdout
    assert "no regression" in result.stdout.lower()


def test_diff_cli_exits_one_and_lists_cell_when_regression(
    cli_runner: CliRunner, tmp_path: Path
) -> None:
    cell = "platform=ios,python=3.12"
    baseline = _write_json(
        tmp_path / "baseline.json", _baseline_payload({cell: 8})
    )
    candidate = _write_json(
        tmp_path / "candidate.json", _baseline_payload({cell: 5})
    )

    result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "diff", "--baseline", str(baseline), "--candidate", str(candidate)],
    )

    assert result.exit_code == 1, result.stdout
    assert "regression" in result.stdout.lower()
    assert cell in result.stdout
    assert "8" in result.stdout
    assert "5" in result.stdout
    assert "-3" in result.stdout


def test_diff_cli_exits_two_when_schema_version_invalid(
    cli_runner: CliRunner, tmp_path: Path
) -> None:
    cell = "platform=ios,python=3.12"
    bad_payload = _baseline_payload({cell: 8})
    bad_payload["schema_version"] = 999
    baseline = _write_json(tmp_path / "baseline.json", bad_payload)
    candidate = _write_json(
        tmp_path / "candidate.json", _baseline_payload({cell: 8})
    )

    result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "diff", "--baseline", str(baseline), "--candidate", str(candidate)],
    )

    assert result.exit_code == 2
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "schema_version" in combined
    assert "999" in combined or "expected 1" in combined


def test_diff_cli_tolerance_absorbs_small_regression(
    cli_runner: CliRunner, tmp_path: Path
) -> None:
    cell = "platform=ios,python=3.12"
    baseline = _write_json(
        tmp_path / "baseline.json", _baseline_payload({cell: 8})
    )
    candidate = _write_json(
        tmp_path / "candidate.json", _baseline_payload({cell: 7})
    )

    result = cli_runner.invoke(
        app,
        [
            "v3a",
            "matrix",
            "diff",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--tolerance",
            "1",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "no regression" in result.stdout.lower()
