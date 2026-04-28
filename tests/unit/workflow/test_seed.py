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


def test_spec_v2_fields(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        """
spec_version: 2
project_type: greenfield
goal: Ship Mobius v2 parser.
constraints:
  - Keep the YAML parser custom.
success_criteria:
  - Parser accepts v2 fields.
non_goals:
  - Do not add YAML dependencies.
verification_commands:
  - command: "uv run pytest tests/unit/workflow/test_seed.py"
    timeout_s: 60
    criterion_ref: B1
    shell: false
risks:
  - description: Parser accepts too much YAML.
    severity: medium
    mitigation: Add explicit unsupported-feature guards.
artifacts:
  - name: Parser tests
    path: tests/unit/workflow/test_seed.py
    type: test
owner: alice
agent_instructions: Keep changes scoped.
""".strip(),
        encoding="utf-8",
    )

    spec = load_seed_spec(spec_path)

    assert spec.spec_version == 2
    assert spec.non_goals == ["Do not add YAML dependencies."]
    assert spec.verification_commands == [
        {
            "command": "uv run pytest tests/unit/workflow/test_seed.py",
            "timeout_s": 60,
            "criterion_ref": "B1",
            "shell": False,
        }
    ]
    assert spec.risks == [
        {
            "description": "Parser accepts too much YAML.",
            "severity": "medium",
            "mitigation": "Add explicit unsupported-feature guards.",
        }
    ]
    assert spec.artifacts == [
        {
            "name": "Parser tests",
            "path": "tests/unit/workflow/test_seed.py",
            "type": "test",
        }
    ]
    assert spec.owner == "alice"
    assert spec.agent_instructions == "Keep changes scoped."
    assert spec.to_event_payload()["verification_commands"][0]["timeout_s"] == 60


def test_parser_rejects_unsupported_yaml(tmp_path: Path) -> None:
    cases = [
        ("anchors", "goal: &goal Ship\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n", "anchor"),
        ("refs", "goal: *goal\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n", "reference"),
        ("tags", "goal: !!str Ship\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n", "tag"),
        (
            "multidoc",
            "---\ngoal: Ship\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n---\ngoal: Again\n",
            "multi-doc",
        ),
        (
            "literal",
            "goal: |\n  Ship\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n",
            "scalar block",
        ),
        (
            "folded",
            "goal: >\n  Ship\nconstraints:\n  - c\nsuccess_criteria:\n  - s\n",
            "scalar block",
        ),
    ]
    for name, content, feature in cases:
        spec_path = tmp_path / f"{name}.yaml"
        spec_path.write_text(content, encoding="utf-8")
        with pytest.raises(SeedSpecValidationError) as exc_info:
            load_seed_spec(spec_path)
        message = str(exc_info.value)
        assert "feature non supportée" in message
        assert feature in message
        assert "ligne" in message


def test_parser_enforces_size_and_depth_limits(tmp_path: Path) -> None:
    large_spec = tmp_path / "large.yaml"
    large_spec.write_text("goal: " + ("x" * (300 * 1024)), encoding="utf-8")
    with pytest.raises(SeedSpecValidationError, match="262144|256"):
        load_seed_spec(large_spec)

    deep_spec = tmp_path / "deep.yaml"
    deep_spec.write_text(
        """
goal: Ship
constraints:
  - c
success_criteria:
  - s
metadata:
  one:
    - two
      three:
        four:
          five: too-deep
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(SeedSpecValidationError, match="depth.*4|4.*depth"):
        load_seed_spec(deep_spec)


def test_owner_list_and_agent_instructions_mapping_forward_compat(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        """
goal: Ship
constraints:
  - c
success_criteria:
  - s
owner:
  - alice
  - bob
agent_instructions:
  claude: Focus on parser tests.
  codex: Keep edits scoped.
""".strip(),
        encoding="utf-8",
    )

    spec = load_seed_spec(spec_path)

    assert spec.owner == ["alice", "bob"]
    assert spec.agent_instructions == {
        "claude": "Focus on parser tests.",
        "codex": "Keep edits scoped.",
    }
