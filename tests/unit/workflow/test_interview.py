from pathlib import Path

import pytest

from mobius.workflow.interview import (
    AmbiguityGateError,
    InterviewFixture,
    compute_ambiguity_score,
    parse_fixture,
    render_spec_yaml,
)


def test_greenfield_weighted_ambiguity_score_passes_with_complete_fixture() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="Build a deterministic CLI workflow.",
        constraints=["No MCP server", "Persist events in SQLite"],
        success=["Spec file generated", "Ambiguity gate passes"],
        context="",
    )

    result = compute_ambiguity_score(fixture)

    assert result.score == 0.0
    assert result.passed is True
    assert result.weights == {"goal": 0.4, "constraints": 0.3, "success": 0.3}


def test_brownfield_score_includes_context_weight() -> None:
    fixture = InterviewFixture(
        project_type="brownfield",
        goal="Replace an existing MCP workflow.",
        constraints=["Keep stdout clean"],
        success=["Help stays fast"],
        context="Existing project uses Typer and SQLite.",
    )

    result = compute_ambiguity_score(fixture)

    assert result.score == 0.0
    assert result.passed is True
    assert result.weights == {"goal": 0.3, "constraints": 0.25, "success": 0.25, "context": 0.2}


def test_ambiguity_gate_fails_above_threshold() -> None:
    fixture = InterviewFixture(
        project_type="brownfield",
        goal="TBD",
        constraints=[],
        success=[],
        context="unknown",
    )

    result = compute_ambiguity_score(fixture)

    assert result.score > 0.2
    assert result.passed is False
    with pytest.raises(AmbiguityGateError):
        result.raise_for_gate()


def test_parse_fixture_accepts_simple_yaml_shape(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.yaml"
    fixture_path.write_text(
        """
project_type: brownfield
goal: Replace an existing workflow with a pure CLI.
constraints:
  - No MCP runtime dependency
  - Logs must use stderr
success:
  - A spec file is created
  - Interview events are persisted
context: Existing codebase already has persistence and config modules.
""".strip(),
        encoding="utf-8",
    )

    fixture = parse_fixture(fixture_path)

    assert fixture.project_type == "brownfield"
    assert fixture.goal == "Replace an existing workflow with a pure CLI."
    assert fixture.constraints == ["No MCP runtime dependency", "Logs must use stderr"]
    assert fixture.success == ["A spec file is created", "Interview events are persisted"]
    assert fixture.context == "Existing codebase already has persistence and config modules."


def test_render_spec_yaml_contains_stable_interview_fields() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="Build a CLI.",
        constraints=["Use Typer"],
        success=["Command exits zero"],
        context="",
    )
    score = compute_ambiguity_score(fixture)

    rendered = render_spec_yaml("interview_test", fixture, score)

    assert "session_id: interview_test" in rendered
    assert "ambiguity_score: 0.0" in rendered
    assert "- Use Typer" in rendered
