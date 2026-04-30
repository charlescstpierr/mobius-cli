"""CLI-level tests for ``mobius v3a matrix score``.

Per PRD F10 and CONTEXT.md, the score CLI emits a canonical JSON file
keyed by ``cell_key`` (declared axis order, never alphabetical) and
auto-disables when the *Spec* has no *Product matrix* declared.

These tests invoke the public Typer app and assert exit codes plus the
on-disk JSON shape — no mocks, no internal helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mobius.cli.main import app


def test_score_cli_writes_empty_scores_and_message_when_no_matrix(
    cli_runner: CliRunner, spec_factory, tmp_path: Path
) -> None:
    spec = spec_factory(tmp_path / "spec.yaml", matrix_block="")
    output = tmp_path / "matrix.json"

    result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(output)],
    )

    assert result.exit_code == 0, result.stdout
    assert "no matrix declared" in result.stdout.lower()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "scores": {}}


def test_score_cli_writes_one_entry_per_cell_for_a_two_by_two_matrix(
    cli_runner: CliRunner, spec_factory, tmp_path: Path
) -> None:
    matrix_block = (
        "matrix:\n  platform:\n    - ios\n    - android\n  python:\n    - '3.12'\n    - '3.13'\n"
    )
    spec = spec_factory(tmp_path / "spec.yaml", matrix_block=matrix_block)
    output = tmp_path / "matrix.json"

    result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(output)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    expected_cells = {
        "platform=ios,python=3.12",
        "platform=ios,python=3.13",
        "platform=android,python=3.12",
        "platform=android,python=3.13",
    }
    assert set(payload["scores"].keys()) == expected_cells
    for cell_payload in payload["scores"].values():
        assert isinstance(cell_payload["score_out_of_10"], int)
        assert 0 <= cell_payload["score_out_of_10"] <= 10
        assert "score_breakdown" in cell_payload


def test_score_cli_produces_byte_identical_output_on_two_invocations(
    cli_runner: CliRunner, spec_factory, tmp_path: Path
) -> None:
    matrix_block = "matrix:\n  platform:\n    - ios\n    - android\n"
    spec = spec_factory(tmp_path / "spec.yaml", matrix_block=matrix_block)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    first_result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(first)],
    )
    second_result = cli_runner.invoke(
        app,
        ["v3a", "matrix", "score", "--spec", str(spec), "--output", str(second)],
    )

    assert first_result.exit_code == 0
    assert second_result.exit_code == 0
    assert first.read_bytes() == second.read_bytes()
    # Canonical JSON envelope: trailing newline + sorted keys at top level.
    text = first.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text.lstrip().startswith("{")
