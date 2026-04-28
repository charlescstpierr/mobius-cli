from mobius.workflow import seed as seed_module


def test_seed_yaml_parses_matrix_nested_lists_and_step_mapping_continuations() -> None:
    parsed = seed_module._parse_simple_yaml(
        """
goal: Ship
matrix:
  platform:
    - ios
    - android
steps:
  - name: Build
    command: "python -m build"
    depends_on:
      - Seed
      - Test
success_criteria:
  - "contains: colon"
""".strip()
    )

    assert parsed["matrix"] == {"platform": ["ios", "android"]}
    assert parsed["steps"] == [
        {
            "name": "Build",
            "command": "python -m build",
            "depends_on": ["Seed", "Test"],
        }
    ]
    assert parsed["success_criteria"] == ["contains: colon"]


def test_seed_yaml_rejects_unexpected_step_list_item() -> None:
    state = seed_module._YamlState("steps:")
    state.current_key = "steps"
    state.container_kind = "list"
    state.result["steps"] = []
    state.pending_item = {"name": "Build"}
    state.pending_item_indent = 2
    state.pending_step_list_key = None

    try:
        state._handle_pending_item_continuation("    - orphan", "- orphan", 4)
    except ValueError as exc:
        assert "unexpected list item inside step" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_seed_yaml_rejects_step_field_mixing_scalar_and_nested_list() -> None:
    state = seed_module._YamlState("steps:")
    state.current_key = "steps"
    state.container_kind = "list"
    state.result["steps"] = []
    state.pending_item = {"name": "Build", "depends_on": "Seed"}
    state.pending_item_indent = 2
    state.pending_step_list_key = "depends_on"

    try:
        state._handle_pending_item_continuation("      - Test", "- Test", 6)
    except ValueError as exc:
        assert "cannot mix scalar and list" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_seed_yaml_rejects_unsupported_pending_item_continuation() -> None:
    state = seed_module._YamlState("steps:")
    state.current_key = "steps"
    state.container_kind = "list"
    state.result["steps"] = []
    state.pending_item = {"name": "Build"}
    state.pending_item_indent = 2

    try:
        state._handle_pending_item_continuation("    nope", "nope", 4)
    except ValueError as exc:
        assert "unsupported spec line" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_seed_yaml_rejects_mapping_and_list_mixing() -> None:
    try:
        seed_module._parse_simple_yaml("metadata:\n  owner: alice\n  - bob\n")
    except ValueError as exc:
        assert "mixes list items" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")

    try:
        seed_module._parse_simple_yaml("constraints:\n  - one\n  owner: alice\n")
    except ValueError as exc:
        assert "mixes mapping entries" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_seed_yaml_rejects_nested_mapping_list_mixing() -> None:
    state = seed_module._YamlState("matrix:")
    state.current_key = "matrix"
    state.container_kind = "mapping"
    state.result["matrix"] = {"platform": "ios"}
    state.active_subkey = "platform"

    try:
        state._handle_list_item("- android", 4)
    except ValueError as exc:
        assert "cannot mix scalar and list" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected ValueError")


def test_seed_text_helpers_cover_optional_and_collection_inputs() -> None:
    assert seed_module._as_optional_text([" alice ", "", "bob"]) == "alice bob"
    assert seed_module._as_optional_text({}) is None
    assert seed_module._as_text_list(None) == []
    assert seed_module._as_text_list([" one ", "", "two"]) == ["one", "two"]
    assert seed_module._as_text_list("solo") == ["solo"]
