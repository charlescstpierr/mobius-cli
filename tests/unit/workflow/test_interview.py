from pathlib import Path

import pytest

from mobius.cli.commands import interview as interview_command
from mobius.cli.main import CliContext
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


def test_interview_writes_output_before_completed_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_path = tmp_path / "fixture.yaml"
    output_path = tmp_path / "spec.yaml"
    fixture_path.write_text(
        """
project_type: greenfield
goal: Produce a durable interview spec.
constraints:
  - Write artifact before completion
success:
  - Completed event only follows an on-disk spec
""".strip(),
        encoding="utf-8",
    )
    original_append_event = interview_command.EventStore.append_event

    def assert_spec_exists_on_completed(
        self: object,
        aggregate_id: str,
        event_type: str,
        payload: object,
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> object:
        if event_type == "interview.completed":
            assert output_path.exists()
            assert output_path.read_text(encoding="utf-8")
        return original_append_event(
            self,  # type: ignore[arg-type]
            aggregate_id,
            event_type,
            payload,  # type: ignore[arg-type]
            sequence=sequence,
            event_id=event_id,
        )

    monkeypatch.setattr(
        interview_command.EventStore,
        "append_event",
        assert_spec_exists_on_completed,
    )

    interview_command.run(
        CliContext(json_output=False, mobius_home=tmp_path / "home"),
        non_interactive=True,
        input_path=fixture_path,
        output_path=output_path,
    )
