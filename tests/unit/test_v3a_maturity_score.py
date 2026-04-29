from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

from mobius.v3a.cli.commands import _override_reason, register, run_maturity
from mobius.v3a.maturity.scorer import (
    render_report,
    score_spec,
    top_up_spec_to_threshold,
)
from mobius.workflow.seed import SeedSpec


def write_spec(path: Path, *, criteria_count: int = 4, with_commands: bool = True) -> None:
    criteria = [
        "Happy path: CLI processes a normal markdown file.",
        "Edge case: empty input exits with a clear error.",
        "Invalid configuration fails with actionable diagnostics.",
        "Timeout behavior is reported without hanging.",
    ][:criteria_count]
    lines = [
        "spec_version: 2",
        "project_type: greenfield",
        "goal: Ship a tiny deterministic CLI.",
        "constraints:",
        "  - deterministic CLI behavior",
        "success_criteria:",
        *[f"  - {criterion}" for criterion in criteria],
    ]
    if with_commands:
        lines.append("verification_commands:")
        for index in range(1, len(criteria) + 1):
            lines.extend(
                [
                    "  - command: uv run pytest -q",
                    f"    criterion_ref: {index}",
                    "    timeout_s: 60",
                    "    shell: true",
                ]
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_maturity_score_is_bounded_and_has_four_dimensions(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    write_spec(spec_path)

    report = score_spec(spec_path)

    assert 0.0 <= report.score <= 1.0
    assert set(report.breakdown) == {
        "verification_coverage",
        "edge_case_coverage",
        "constraint_coverage",
        "ambiguity_and_lemma",
    }
    assert len(report.breakdown) == 4


def test_maturity_score_is_deterministic_without_llm_calls(tmp_path: Path, monkeypatch) -> None:
    spec_path = tmp_path / "spec.yaml"
    write_spec(spec_path)

    def fail_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "llm" in name.lower():
            raise AssertionError(f"unexpected LLM import: {name}")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    first = score_spec(spec_path).to_dict()
    second = score_spec(spec_path).to_dict()

    assert first == second


def test_auto_top_up_reaches_threshold_minimally(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    write_spec(spec_path, criteria_count=2, with_commands=False)

    before = score_spec(spec_path)
    top_up = top_up_spec_to_threshold(spec_path)

    assert before.score < 0.8
    assert top_up.questions_asked > 0
    assert top_up.after.score >= 0.8
    assert score_spec(spec_path).score >= 0.8


def test_auto_top_up_is_noop_for_mature_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    write_spec(spec_path)

    top_up = top_up_spec_to_threshold(spec_path)

    assert top_up.questions_asked == 0
    assert top_up.before.to_dict() == top_up.after.to_dict()


def test_maturity_handles_direct_seed_spec_edge_paths() -> None:
    empty = SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Ship deterministic output.",
        constraints=[],
        success_criteria=[],
        context="",
        metadata={"ambiguity_score": "not-a-float"},
    )
    empty_report = score_spec(empty)
    assert empty_report.score == 0.125

    risk_only_edge = SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Ship deterministic output.",
        constraints=[],
        success_criteria=["User receives a useful result."],
        context="",
        verification_commands=[
            {
                "command": "pytest verifies User receives a useful result.",
                "timeout_s": 60,
                "shell": True,
            }
        ],
        risks=[{"description": "empty input error path", "severity": "low"}],
    )
    report = score_spec(risk_only_edge)
    assert report.details["edge_case_ratio"] == 1.0
    assert report.details["constraint_ratio"] == 0.0


def test_auto_top_up_adds_constraint_and_lemma_when_needed(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    repeated = "Same repeated success text."
    lines = [
        "spec_version: 2",
        "project_type: greenfield",
        "goal: Ship a small CLI.",
        "constraints:",
        "  - preserve offline cache",
        "success_criteria:",
        f"  - {repeated}",
        f"  - {repeated}",
        f"  - {repeated}",
        "verification_commands:",
        "  - command: uv run pytest -q",
        "    criterion_ref: 1",
        "    timeout_s: 60",
        "    shell: true",
        "  - command: uv run pytest -q",
        "    criterion_ref: 2",
        "    timeout_s: 60",
        "    shell: true",
        "  - command: uv run pytest -q",
        "    criterion_ref: 3",
        "    timeout_s: 60",
        "    shell: true",
    ]
    spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    top_up = top_up_spec_to_threshold(spec_path)
    text = spec_path.read_text(encoding="utf-8")

    assert top_up.after.score >= 0.8
    assert "Constraint coverage:" in text or "Operational telemetry" in text


def test_render_and_standalone_maturity_json_cover_rich_spec_paths(
    tmp_path: Path,
    capsys,
) -> None:
    spec = SeedSpec(
        source_session_id="interview-rich",
        project_type="greenfield",
        goal="Ship deterministic output.",
        constraints=["deterministic behavior"],
        success_criteria=["Edge case: invalid input reports an error."],
        context="",
        non_goals=["network services"],
        verification_commands=[
            {"command": "uv run pytest -q", "criterion_ref": "1", "timeout_s": 60, "shell": True}
        ],
        risks=[{"description": "malformed input", "severity": "low", "mitigation": "test it"}],
        owner=["agent", "human"],
        agent_instructions={"claude": "keep state local"},
    )
    report = score_spec(spec)
    assert "breakdown:" in render_report(report)

    spec_path = tmp_path / "spec.yaml"
    write_spec(spec_path)
    run_maturity(SimpleNamespace(), spec=spec_path, json_output=True)

    assert '"score"' in capsys.readouterr().out

    run_maturity(SimpleNamespace(), spec=spec_path, json_output=False)
    assert "Mobius v3a Maturity Report" in capsys.readouterr().out


def test_override_reason_uses_explicit_or_non_interactive_default() -> None:
    assert _override_reason(" operator accepted risk ") == "operator accepted risk"
    assert _override_reason(None) == "non-interactive --force-immature override"


def test_v3a_register_exposes_build_command_help() -> None:
    app = typer.Typer()
    register(app)

    result = CliRunner().invoke(app, ["build", "--help"])

    assert result.exit_code == 0
    assert "--auto-top-up" in result.stdout
