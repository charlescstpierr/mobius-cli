"""Branch coverage for the interview fixture parser and ambiguity gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobius.workflow.interview import (
    AmbiguityGateError,
    AmbiguityScore,
    InterviewFixture,
    compute_ambiguity_score,
    parse_fixture,
    question_answers,
    render_spec_yaml,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_fixture_rejects_invalid_project_type(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "f.yaml", "project_type: marsfield\n")
    with pytest.raises(ValueError, match="project_type"):
        parse_fixture(fixture)


def test_parse_fixture_yaml_unsupported_line_raises(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "f.yaml", "no colon line\n")
    with pytest.raises(ValueError, match="unsupported fixture line"):
        parse_fixture(fixture)


def test_parse_fixture_yaml_orphan_list_raises(tmp_path: Path) -> None:
    fixture = _write(tmp_path / "f.yaml", "- orphan\n")
    with pytest.raises(ValueError, match="list item without preceding key"):
        parse_fixture(fixture)


def test_parse_fixture_non_brace_input_uses_yaml_path(tmp_path: Path) -> None:
    """Inputs that don't begin with '{' are parsed as YAML, which rejects arrays."""
    fixture = _write(tmp_path / "f.json", '["array"]\n')
    with pytest.raises(ValueError):
        parse_fixture(fixture)


def test_parse_fixture_skips_comments_and_blanks(tmp_path: Path) -> None:
    fixture = _write(
        tmp_path / "f.yaml",
        """
# top comment

project_type: greenfield
goal: "g"
constraints:
  # commented item
  - c1
success:
  - s1
""".strip(),
    )
    parsed = parse_fixture(fixture)
    assert parsed.goal == "g"
    assert parsed.constraints == ["c1"]
    assert parsed.success == ["s1"]


def test_parse_fixture_brownfield_records_context(tmp_path: Path) -> None:
    fixture = _write(
        tmp_path / "f.yaml",
        """
project_type: brownfield
goal: g
constraints:
  - c
success:
  - s
context: existing-context
""".strip(),
    )
    parsed = parse_fixture(fixture)
    assert parsed.is_brownfield
    assert parsed.context == "existing-context"


def test_compute_ambiguity_score_brownfield_includes_context_weight() -> None:
    fixture = InterviewFixture(
        project_type="brownfield",
        goal="real goal",
        constraints=["c1"],
        success=["s1"],
        context="real context",
    )
    score = compute_ambiguity_score(fixture)
    assert score.passed is True
    assert "context" in score.weights
    assert score.score == 0.0


def test_compute_ambiguity_score_high_when_ambiguous() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="TBD",
        constraints=["", "tbd"],
        success=["?"],
        context="",
    )
    score = compute_ambiguity_score(fixture)
    assert isinstance(score, AmbiguityScore)
    assert score.passed is False
    with pytest.raises(AmbiguityGateError, match="exceeds gate"):
        score.raise_for_gate()


def test_render_spec_yaml_round_trips_brownfield() -> None:
    fixture = InterviewFixture(
        project_type="brownfield",
        goal="real goal",
        constraints=["alpha", "beta"],
        success=["one"],
        context="ctx",
    )
    score = compute_ambiguity_score(fixture)
    text = render_spec_yaml("interview_xyz", fixture, score)
    assert text.startswith("session_id: interview_xyz")
    assert "context: ctx" in text
    assert "constraints:" in text


def test_render_spec_yaml_quotes_special_strings() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="goal: with colon",
        constraints=["c"],
        success=["s"],
        context="",
    )
    score = compute_ambiguity_score(fixture)
    text = render_spec_yaml("session_x", fixture, score)
    assert '"goal: with colon"' in text


def test_render_spec_yaml_handles_empty_lists() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="",
        constraints=[],
        success=[],
        context="",
    )
    score = compute_ambiguity_score(fixture)
    text = render_spec_yaml("s", fixture, score)
    assert "constraints:\n  []" in text


def test_question_answers_brownfield_includes_context() -> None:
    fixture = InterviewFixture(
        project_type="brownfield",
        goal="g",
        constraints=["c"],
        success=["s"],
        context="ctx",
    )
    triples = question_answers(fixture)
    keys = [key for key, _, _ in triples]
    assert "context" in keys


def test_question_answers_greenfield_omits_context() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="g",
        constraints=["c"],
        success=["s"],
        context="",
    )
    triples = question_answers(fixture)
    keys = [key for key, _, _ in triples]
    assert "context" not in keys


def test_parse_fixture_json_round_trip(tmp_path: Path) -> None:
    fixture = _write(
        tmp_path / "f.json",
        """{
  "project_type": "greenfield",
  "goal": "g",
  "constraints": ["c"],
  "success": ["s"]
}
""",
    )
    parsed = parse_fixture(fixture)
    assert parsed.constraints == ["c"]
    assert parsed.success == ["s"]
