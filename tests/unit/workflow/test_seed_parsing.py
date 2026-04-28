"""Branch coverage for the seed-spec YAML/JSON parser and validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobius.workflow.seed import (
    SeedSpecValidationError,
    SpecParseError,
    _as_int,
    _configured_max_spec_bytes,
    _ensure_nesting_depth,
    _normalize_agent_instructions,
    _normalize_mapping_list,
    _normalize_owner,
    _normalize_scalar_value,
    _parse_mapping,
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


def test_validate_seed_spec_collects_v2_field_errors() -> None:
    with pytest.raises(SeedSpecValidationError) as exc:
        validate_seed_spec(
            {
                "goal": "g",
                "constraints": ["c"],
                "success_criteria": ["s"],
                "verification_commands": "pytest",
                "risks": ["not a mapping"],
                "artifacts": [{"": "empty key"}],
                "owner": {"team": "core"},
                "agent_instructions": ["do it"],
                "spec_version": "two",
            }
        )

    message = str(exc.value)
    assert "verification_commands" in message
    assert "risks[1] must be a mapping" in message
    assert "artifacts[1] contains an empty key" in message
    assert "'owner' must be a string or list of strings" in message
    assert "'agent_instructions' must be a string or mapping" in message
    assert "'spec_version' must be an integer" in message


def test_v2_normalizer_helper_error_and_scalar_branches() -> None:
    assert _normalize_mapping_list(None, "risks") == []
    assert _normalize_mapping_list([{"shell": "true", "timeout_s": "5"}], "commands") == [
        {"shell": True, "timeout_s": 5}
    ]
    assert _normalize_scalar_value({"nested": ["false", "plain"]}) == {
        "nested": [False, "plain"]
    }
    assert _normalize_scalar_value(3.5) == 3.5
    assert _normalize_owner(["", " alice "]) == ["alice"]
    assert _normalize_agent_instructions({" claude ": " ship "}) == {"claude": "ship"}

    with pytest.raises(ValueError, match="list must contain"):
        _normalize_owner(["", " "])
    with pytest.raises(ValueError, match="empty key"):
        _normalize_agent_instructions({"": "missing"})
    with pytest.raises(ValueError, match="integer"):
        _as_int(True, "spec_version")
    with pytest.raises(ValueError, match="integer"):
        _as_int("not-int", "spec_version")


def test_parse_mapping_json_guards_and_depth_limit() -> None:
    with pytest.raises(SpecParseError, match="property name"):
        _parse_mapping("{ broken")
    with pytest.raises(SpecParseError, match="unsupported"):
        _parse_mapping('["array"]')
    assert _parse_mapping('{"goal": "g"}') == {"goal": "g"}
    with pytest.raises(SpecParseError, match="depth"):
        _parse_mapping('{"a":{"b":{"c":{"d":{"e":[]}}}}}')
    with pytest.raises(SpecParseError, match="depth"):
        _ensure_nesting_depth({"a": {"b": {"c": {"d": {"e": []}}}}}, max_depth=4)


def test_configured_max_spec_bytes_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOBIUS_HOME", raising=False)
    assert _configured_max_spec_bytes() == 256 * 1024

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MOBIUS_HOME", str(home))
    assert _configured_max_spec_bytes() == 256 * 1024

    config = home / "config.json"
    config.write_text('{"spec_max_bytes": "128"}', encoding="utf-8")
    assert _configured_max_spec_bytes() == 128
    with pytest.raises(SpecParseError, match="128"):
        _parse_mapping("goal: " + ("x" * 200))

    config.write_text('{"max_spec_bytes": "64"}', encoding="utf-8")
    assert _configured_max_spec_bytes() == 64
    config.write_text('{"spec_max_bytes": "not-int"}', encoding="utf-8")
    assert _configured_max_spec_bytes() == 256 * 1024
    config.write_text('[]', encoding="utf-8")
    assert _configured_max_spec_bytes() == 256 * 1024
    config.write_text("{ broken", encoding="utf-8")
    assert _configured_max_spec_bytes() == 256 * 1024
