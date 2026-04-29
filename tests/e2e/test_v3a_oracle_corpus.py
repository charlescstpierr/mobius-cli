from __future__ import annotations

from pathlib import Path

from mobius.v3a.interview.oracle import propose_verifications
from mobius.v3a.interview.runner import run_interview


def test_full_interview_transcript_oracle_proposes_for_eighty_percent(
    tmp_path: Path,
) -> None:
    result = run_interview(
        intent="tiny TODO CLI",
        run_id="oracle-e2e",
        output_dir=tmp_path,
        auto_confirm=False,
        answers=[
            "Ship a tiny TODO CLI with add, list, and done commands.",
            "Keep all state local and deterministic.",
            "CLI command returns exit code 2 for empty input.",
            "End-to-end test creates one item, lists it, completes it, and verifies output.",
            "Ruff linting and mypy type checking stay clean.",
            "Workflow smoke test completes before release.",
        ],
    )
    transcript = result.transcript_path.read_text(encoding="utf-8")

    report = propose_verifications(result.fixture.success, transcript=transcript)

    assert report.criterion_count >= 5
    assert report.proposed_criteria_rate >= 0.80
    assert report.heuristic_coverage_rate >= 0.80
    assert all(command["criterion_ref"].startswith("C") for command in report.all_commands)
    assert any(
        command["command"] == "uv run pytest -q tests/e2e/cli"
        for command in report.all_commands
    )
