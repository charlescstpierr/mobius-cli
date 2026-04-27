"""Branch-coverage tests for v0.1.4 additions.

Targets the seed parser, template registry, and interview helper paths
that were added or extended in v0.1.4 and that are not exercised by the
behavioural tests.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from mobius.workflow import templates
from mobius.workflow.interview import (
    fixture_from_template,
    run_interactive_interview,
)
from mobius.workflow.seed import (
    SeedSpecValidationError,
    _parse_mapping,
    validate_seed_spec,
)


def parse_seed_spec_text(text: str):  # type: ignore[no-untyped-def]
    return validate_seed_spec(_parse_mapping(text))


# --- seed.py edge cases ---------------------------------------------------


def test_seed_rejects_unknown_top_level_key() -> None:
    text = "project_type: greenfield\ngoal: do x\nconstraints: []\nsuccess_criteria: []\nbogus: 1\n"
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "unknown spec key" in str(excinfo.value) and "'bogus'" in str(excinfo.value)


def test_seed_steps_must_be_list() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "steps: not-a-list\n"
    )
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "steps" in str(excinfo.value).lower()


def test_seed_steps_depends_on_unknown_step() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "steps:\n"
        "  - name: build\n"
        "    depends_on:\n"
        "      - missing\n"
    )
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "depends_on" in str(excinfo.value)


def test_seed_matrix_must_be_mapping() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "matrix:\n"
        "  - oops\n"
    )
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "matrix" in str(excinfo.value).lower()


def test_seed_matrix_empty_axis_name_rejected() -> None:
    """Empty axis name (after stripping) should be rejected."""
    from mobius.workflow.seed import _normalize_matrix

    with pytest.raises(ValueError):
        _normalize_matrix({"": ["a"]})


def test_seed_matrix_axis_requires_values() -> None:
    """Programmatic call with empty axis values is rejected."""
    from mobius.workflow.seed import _normalize_matrix

    with pytest.raises(ValueError):
        _normalize_matrix({"platform": []})


def test_seed_metadata_must_be_mapping() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "metadata:\n"
        "  - oops\n"
    )
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "metadata" in str(excinfo.value).lower()


def test_seed_duplicate_step_name_is_rejected() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "steps:\n"
        "  - name: build\n"
        "  - name: build\n"
    )
    with pytest.raises(SeedSpecValidationError) as excinfo:
        parse_seed_spec_text(text)
    assert "duplicate" in str(excinfo.value).lower()


def test_seed_steps_string_form_is_accepted() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "steps:\n"
        "  - bootstrap\n"
        "  - build\n"
    )
    spec = parse_seed_spec_text(text)
    assert [step.name for step in spec.steps] == ["bootstrap", "build"]


def test_seed_unexpected_indented_line_without_parent() -> None:
    text = "  oops: 1\n"
    with pytest.raises(SeedSpecValidationError):
        parse_seed_spec_text(text)


def test_seed_unsupported_line_no_colon() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints:\n"
        "  rubbish-line-without-colon-or-dash\n"
    )
    with pytest.raises(ValueError):
        parse_seed_spec_text(text)


def test_seed_step_with_nested_command_and_depends_list() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "steps:\n"
        "  - name: a\n"
        "    command: echo a\n"
        "  - name: b\n"
        "    command: echo b\n"
        "    depends_on:\n"
        "      - a\n"
    )
    spec = parse_seed_spec_text(text)
    names = [step.name for step in spec.steps]
    assert names == ["a", "b"]
    b = next(s for s in spec.steps if s.name == "b")
    assert b.depends_on == ("a",)


def test_seed_matrix_with_nested_list_values() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "matrix:\n"
        "  platform:\n"
        "    - ios\n"
        "    - android\n"
    )
    spec = parse_seed_spec_text(text)
    assert spec.matrix == {"platform": ["ios", "android"]}


def test_seed_step_dict_without_name_rejected() -> None:
    from mobius.workflow.seed import _normalize_steps

    with pytest.raises(ValueError) as excinfo:
        _normalize_steps([{"command": "echo"}])
    assert "name" in str(excinfo.value)


def test_seed_step_invalid_type_rejected() -> None:
    from mobius.workflow.seed import _normalize_steps

    with pytest.raises(ValueError):
        _normalize_steps([42])


def test_seed_step_empty_string_rejected() -> None:
    from mobius.workflow.seed import _normalize_steps

    with pytest.raises(ValueError):
        _normalize_steps([""])


def test_seed_metadata_empty_key_rejected() -> None:
    from mobius.workflow.seed import _normalize_metadata

    with pytest.raises(ValueError):
        _normalize_metadata({"": "v"})


def test_seed_yaml_mixes_list_with_mapping_then_list_raises() -> None:
    """First a list item, then a mapping entry under same key."""
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints:\n"
        "  - one\n"
        "  two: 2\n"
    )
    with pytest.raises(ValueError):
        parse_seed_spec_text(text)


def test_seed_yaml_mixes_mapping_then_list_raises() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints:\n"
        "  one: 1\n"
        "  - two\n"
    )
    with pytest.raises(ValueError):
        parse_seed_spec_text(text)


def test_seed_metadata_simple_mapping() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "metadata:\n"
        "  owner: alice\n"
        "  team: core\n"
    )
    spec = parse_seed_spec_text(text)
    assert spec.metadata == {"owner": "alice", "team": "core"}


def test_seed_template_field_round_trips() -> None:
    text = (
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints: []\n"
        "success_criteria: []\n"
        "template: web\n"
    )
    spec = parse_seed_spec_text(text)
    assert spec.template == "web"


# --- templates.py edge cases ----------------------------------------------


def test_render_spec_for_each_known_template() -> None:
    for name in ["web", "cli", "lib", "etl", "mobile", "docs", "blank"]:
        template = templates.get_template(name)
        rendered = templates.render_spec(template)
        assert "project_type" in rendered
        spec = parse_seed_spec_text(rendered)
        assert spec.project_type == "greenfield"


def test_detect_template_for_empty_returns_blank(tmp_path: Path) -> None:
    detected = templates.detect_template(tmp_path)
    assert detected == "blank"


def test_detect_template_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert templates.detect_template(tmp_path) == "web"


def test_detect_template_python_lib(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n", encoding="utf-8"
    )
    assert templates.detect_template(tmp_path) == "lib"


def test_detect_template_rust_cli(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    assert templates.detect_template(tmp_path) == "cli"


def test_detect_template_etl(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    assert templates.detect_template(tmp_path) == "etl"


def test_detect_template_mobile_pubspec(tmp_path: Path) -> None:
    (tmp_path / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
    assert templates.detect_template(tmp_path) == "mobile"


def test_detect_template_docs_mkdocs(tmp_path: Path) -> None:
    (tmp_path / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    assert templates.detect_template(tmp_path) == "docs"


def test_detect_template_nonexistent_workspace(tmp_path: Path) -> None:
    assert templates.detect_template(tmp_path / "does-not-exist") == "blank"


def test_get_template_unknown_falls_back_to_blank() -> None:
    template = templates.get_template("does-not-exist")
    assert template.name == "blank"


# --- interview.py edge cases ----------------------------------------------


def test_fixture_from_template_returns_blank_defaults() -> None:
    template = templates.get_template("web")
    fixture = fixture_from_template(template)
    assert fixture.template == "web"
    assert fixture.constraints  # web template has at least one constraint


def test_interactive_interview_accepts_all_defaults_via_eof(tmp_path: Path) -> None:
    """When stdin reaches EOF before each question, the function falls
    back to the per-template defaults rather than crashing."""
    stdin = io.StringIO("")
    stderr = io.StringIO()
    fixture = run_interactive_interview(
        workspace=tmp_path,
        template_name="web",
        stdin=stdin,
        stderr=stderr,
    )
    assert fixture.template == "web"
    # The web template provides default constraints/success_criteria; the
    # interactive driver should have fallen back to them after EOF.
    assert fixture.goal


def test_interactive_interview_brownfield_collects_context(tmp_path: Path) -> None:
    """Brownfield project_type triggers the optional 'context' prompt."""
    stdin_text = "brownfield\nDeliver Y\n\n\nMaintain old API\n"
    stdin = io.StringIO(stdin_text)
    stderr = io.StringIO()
    fixture = run_interactive_interview(
        workspace=tmp_path,
        template_name="lib",
        stdin=stdin,
        stderr=stderr,
    )
    assert fixture.project_type == "brownfield"
    assert fixture.context  # context prompt was reached


# --- cancel.py edge cases -------------------------------------------------


def test_cancel_terminate_process_already_dead() -> None:
    from mobius.workflow.cancel import _terminate_process

    # PID 0 raises ProcessLookupError synchronously on Darwin/Linux when used
    # with signal 15 against a non-existent process. Use a giant pid that is
    # extremely unlikely to exist.
    assert _terminate_process(2_147_483_646, grace_period=0.0) is False


def test_cancel_has_event_returns_false_when_store_missing(tmp_path: Path) -> None:
    from mobius.config import get_paths
    from mobius.workflow.cancel import _has_event

    paths = get_paths(tmp_path / "home")
    # Event store file does not exist yet.
    assert _has_event(paths, "run_x", "run.cancelled") is False


def test_cancel_ensure_status_noop_when_store_missing(tmp_path: Path) -> None:
    from mobius.config import get_paths
    from mobius.workflow.cancel import _ensure_status_cancelled

    paths = get_paths(tmp_path / "home")
    # Should silently return without raising.
    _ensure_status_cancelled(paths, "run_x")


def test_cancel_ensure_status_updates_running_session(tmp_path: Path) -> None:
    from mobius.config import get_paths
    from mobius.persistence.event_store import EventStore
    from mobius.workflow.cancel import _ensure_status_cancelled

    paths = get_paths(tmp_path / "home")
    with EventStore(paths.event_store) as store:
        store.create_session("run_x", runtime="run", status="running")
    _ensure_status_cancelled(paths, "run_x")
    with EventStore(paths.event_store) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id=?", ("run_x",)
        ).fetchone()
    assert row["status"] == "cancelled"
