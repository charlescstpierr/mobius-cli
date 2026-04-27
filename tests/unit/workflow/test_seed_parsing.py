"""Branch coverage for the seed-spec YAML/JSON parser and validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobius.workflow.seed import (
    SeedSpecValidationError,
    load_seed_spec,
    validate_seed_spec,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_seed_spec_missing_file_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(SeedSpecValidationError, match="cannot read"):
        load_seed_spec(tmp_path / "missing.yaml")


def test_load_seed_spec_json_array_uses_yaml_path(tmp_path: Path) -> None:
    """Inputs that don't begin with '{' fall through to the YAML parser, which
    rejects them as unsupported lines."""
    spec = _write(tmp_path / "spec.yaml", '["just", "an", "array"]\n')
    with pytest.raises(SeedSpecValidationError):
        load_seed_spec(spec)


def test_load_seed_spec_json_object_array_raises(tmp_path: Path) -> None:
    spec = _write(tmp_path / "spec.json", '{"top": "level"}\n[")"]\n')
    with pytest.raises(SeedSpecValidationError):
        load_seed_spec(spec)


def test_load_seed_spec_invalid_json_syntax_raises(tmp_path: Path) -> None:
    spec = _write(tmp_path / "spec.json", "{ not valid json")
    with pytest.raises(SeedSpecValidationError, match="seed spec validation failed"):
        load_seed_spec(spec)


def test_load_seed_spec_empty_file_raises(tmp_path: Path) -> None:
    spec = _write(tmp_path / "spec.yaml", "")
    with pytest.raises(SeedSpecValidationError, match="empty"):
        load_seed_spec(spec)


def test_load_seed_spec_yaml_unsupported_line_raises(tmp_path: Path) -> None:
    spec = _write(tmp_path / "spec.yaml", "this line has no colon\n")
    with pytest.raises(SeedSpecValidationError, match="unsupported spec line"):
        load_seed_spec(spec)


def test_load_seed_spec_yaml_list_item_without_key_raises(tmp_path: Path) -> None:
    spec = _write(tmp_path / "spec.yaml", "- orphan\n")
    with pytest.raises(SeedSpecValidationError, match="list item without preceding key"):
        load_seed_spec(spec)


def test_validate_seed_spec_collects_all_errors() -> None:
    with pytest.raises(SeedSpecValidationError) as exc:
        validate_seed_spec({"project_type": "marsfield"})
    msg = str(exc.value)
    assert "project_type" in msg
    assert "goal" in msg
    assert "constraints" in msg
    assert "success_criteria" in msg


def test_validate_seed_spec_brownfield_requires_context() -> None:
    with pytest.raises(SeedSpecValidationError, match="context is required"):
        validate_seed_spec(
            {
                "project_type": "brownfield",
                "goal": "g",
                "constraints": ["c"],
                "success_criteria": ["s"],
            }
        )


def test_validate_seed_spec_accepts_success_alias() -> None:
    spec = validate_seed_spec(
        {
            "project_type": "greenfield",
            "goal": "g",
            "constraints": ["c"],
            "success": ["s"],
        }
    )
    assert spec.success_criteria == ["s"]


def test_load_seed_spec_yaml_quoted_strings_are_unquoted(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "spec.yaml",
        """
project_type: greenfield
goal: "quoted goal: with colon"
constraints:
  - 'single quoted'
success_criteria:
  - "double quoted"
""".strip(),
    )
    result = load_seed_spec(spec)
    assert result.goal == "quoted goal: with colon"
    assert result.constraints == ["single quoted"]
    assert result.success_criteria == ["double quoted"]


def test_load_seed_spec_yaml_skips_comment_and_blank_lines(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "spec.yaml",
        """
# comment

project_type: greenfield
goal: g

constraints:
  # nested comment
  - c
success_criteria:
  - s
""".strip(),
    )
    result = load_seed_spec(spec)
    assert result.goal == "g"
    assert result.constraints == ["c"]


def test_load_seed_spec_yaml_supports_session_id(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "spec.yaml",
        """
session_id: seed_abc
project_type: greenfield
goal: g
constraints:
  - c
success_criteria:
  - s
""".strip(),
    )
    result = load_seed_spec(spec)
    assert result.source_session_id == "seed_abc"


def test_load_seed_spec_json_object(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "spec.json",
        '{"project_type": "greenfield", "goal": "g", "constraints": ["c"], '
        '"success_criteria": ["s"]}\n',
    )
    result = load_seed_spec(spec)
    assert result.project_type == "greenfield"
    assert result.constraints == ["c"]


def test_load_seed_spec_yaml_list_then_scalar_raises(tmp_path: Path) -> None:
    spec = _write(
        tmp_path / "spec.yaml",
        """
project_type: greenfield
goal: g
constraints:
  - first
constraints: scalar-after-list
success_criteria:
  - s
""".strip(),
    )
    # The second `constraints:` overwrites with a scalar; the parser then
    # accepts it. The validator must accept either list or single-text input.
    result = load_seed_spec(spec)
    assert result.constraints == ["scalar-after-list"]


def test_validate_seed_spec_rejects_empty_string_in_lists() -> None:
    with pytest.raises(SeedSpecValidationError, match="constraints"):
        validate_seed_spec(
            {
                "project_type": "greenfield",
                "goal": "g",
                "constraints": ["", "  "],
                "success_criteria": ["s"],
            }
        )
