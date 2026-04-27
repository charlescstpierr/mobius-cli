from pathlib import Path

import pytest

from mobius.workflow.seed import SeedSpecValidationError, load_seed_spec


def test_load_seed_spec_accepts_interview_spec_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        """
session_id: interview_123
project_type: brownfield
ambiguity_score: 0.0
ambiguity_gate: 0.2
ambiguity_components:
  goal: 0.0
  constraints: 0.0
  success: 0.0
  context: 0.0
goal: Replace MCP with a CLI.
constraints:
  - Preserve stdout discipline
success_criteria:
  - Seed events are persisted
context: Existing Typer CLI and event store are present.
""".strip(),
        encoding="utf-8",
    )

    spec = load_seed_spec(spec_path)

    assert spec.source_session_id == "interview_123"
    assert spec.project_type == "brownfield"
    assert spec.goal == "Replace MCP with a CLI."
    assert spec.constraints == ["Preserve stdout discipline"]
    assert spec.success_criteria == ["Seed events are persisted"]
    assert spec.context == "Existing Typer CLI and event store are present."


def test_load_seed_spec_reports_clear_validation_errors(tmp_path: Path) -> None:
    spec_path = tmp_path / "invalid.yaml"
    spec_path.write_text(
        """
project_type: spaceship
goal:
constraints:
success_criteria:
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(SeedSpecValidationError) as exc_info:
        load_seed_spec(spec_path)

    message = str(exc_info.value)
    assert "seed spec validation failed" in message
    assert "project_type must be either 'greenfield' or 'brownfield'" in message
    assert "goal is required" in message
    assert "constraints must contain at least one item" in message
    assert "success_criteria must contain at least one item" in message
