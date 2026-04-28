from __future__ import annotations

from pathlib import Path

import pytest

from mobius.persistence.event_store import EventStore
from mobius.workflow import handoff
from mobius.workflow.handoff import generate_handoff, render_handoff
from mobius.workflow.seed import SeedSpec, SeedSpecValidationError, load_seed_spec


def _write_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Produce a contract-compliant handoff.
constraints:
  - Preserve literal section markers.
success_criteria:
  - C1
verification_commands:
  - command: "python -c 'print(1)'"
    criterion_ref: C1
risks:
  - id: drift
    mitigation: Test every known agent.
owner: qa-team
non_goals:
  - Do not add dependencies.
agent_instructions: Follow repository validators before handoff.
""".strip(),
        encoding="utf-8",
    )


def test_handoff_includes_all_sections(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(spec_path)

    rendered = render_handoff(load_seed_spec(spec_path), agent="claude")

    assert "<GOAL>" in rendered.prompt
    assert "<CRITERIA>" in rendered.prompt
    assert "<COMMANDS>" in rendered.prompt
    assert "<RISKS>" in rendered.prompt
    assert "<INSTRUCTIONS>" in rendered.prompt
    assert "Produce a contract-compliant handoff." in rendered.prompt
    assert "verdict=pass C1" in rendered.prompt
    assert "python -c 'print(1)'" in rendered.prompt
    assert "Follow repository validators" in rendered.prompt


def test_generate_handoff_emits_versioned_event(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    _write_spec(spec_path)
    store_path = tmp_path / "home" / "events.db"

    rendered = generate_handoff(
        event_store_path=store_path,
        spec_path=spec_path,
        agent="codex",
        dry_run=True,
    )

    assert rendered.agent == "codex"
    with EventStore(store_path, read_only=True) as store:
        events = store.read_events(f"handoff:{spec_path.resolve()}")
    generated = [event for event in events if event.type == "handoff.generated"]
    assert len(generated) == 1
    payload = generated[0].payload_data
    assert payload["agent"] == "codex"
    assert payload["template_version"] == 1
    assert payload["criteria_count"] == 1
    assert payload["dry_run"] is True


def test_handoff_formats_empty_sections_and_omits_empty_instructions() -> None:
    spec = SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Handle sparse specs.",
        constraints=["Stay deterministic."],
        success_criteria=[],
        context="",
        agent_instructions={},
    )

    rendered = render_handoff(spec, agent="claude")

    assert "<GOAL>" in rendered.prompt
    assert "<CRITERIA>\n- (none)" in rendered.prompt
    assert "<COMMANDS>\n- (none)" in rendered.prompt
    assert "<RISKS>\n- (none)" in rendered.prompt
    assert "<INSTRUCTIONS>" not in rendered.prompt


def test_handoff_formats_list_refs_timeouts_and_empty_risk() -> None:
    spec = SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Format rich handoff fields.",
        constraints=["Stay deterministic."],
        success_criteria=["Alpha criterion.", "Beta criterion."],
        context="",
        verification_commands=[
            {
                "command": "pytest -q",
                "criterion_refs": ["Alpha", "Beta criterion."],
                "timeout_s": 7,
            },
            {"command": "ruff check", "criteria": ["unmatched"]},
        ],
        risks=[{}, {"description": "Nested value", "tags": ["handoff", "contract"]}],
    )

    rendered = render_handoff(spec, agent="codex")

    assert "timeout_s=7" in rendered.prompt
    assert 'criterion_ref: ["Alpha", "Beta criterion."]' in rendered.prompt
    assert "verdict=pass Alpha criterion." in rendered.prompt
    assert "verdict=pass Beta criterion." in rendered.prompt
    assert "- (empty)" in rendered.prompt
    assert 'tags: ["handoff", "contract"]' in rendered.prompt


def test_handoff_rejects_unknown_agent_and_missing_template() -> None:
    spec = SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Reject bad agents.",
        constraints=["Stay deterministic."],
        success_criteria=["C1"],
        context="",
    )

    with pytest.raises(ValueError, match="unknown handoff agent"):
        render_handoff(spec, agent="unknown")
    with pytest.raises(ValueError, match="missing handoff template"):
        handoff._load_template("unknown")


def test_handoff_aggregate_id_wraps_resolve_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_resolve(self: Path) -> Path:
        raise OSError("boom")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(SeedSpecValidationError, match="cannot resolve spec path"):
        handoff._handoff_aggregate_id(Path("spec.yaml"))
