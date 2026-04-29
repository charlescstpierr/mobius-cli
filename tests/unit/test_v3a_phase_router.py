from __future__ import annotations

from pathlib import Path

from mobius.v3a.phase_router.transitions import (
    RouterCommand,
    narrative_line,
    parse_router_command,
    transition_from,
)


def test_phase_router_transitions_are_deterministic() -> None:
    command = parse_router_command(":next")
    assert command is not None
    assert command.kind is RouterCommand.NEXT
    assert transition_from("interview", command) == "seed"
    assert transition_from("interview", command) == "seed"


def test_phase_router_accepts_universal_keystrokes() -> None:
    assert parse_router_command(":next") is not None
    assert parse_router_command(":back") is not None
    assert parse_router_command(":back 2") is not None
    assert parse_router_command(":explain") is not None
    assert parse_router_command(":stop") is not None
    assert parse_router_command(":why") is not None


def test_phase_router_rejects_invalid_or_empty_commands() -> None:
    assert parse_router_command("") is None
    assert parse_router_command(":back many") is None
    assert parse_router_command(":back 0") is None
    assert parse_router_command(":unknown") is None


def test_phase_router_back_count_moves_to_prior_phase() -> None:
    command = parse_router_command(":back 2")
    assert command is not None

    assert transition_from("scoring", command) == "seed"


def test_phase_router_stop_and_explain_transitions() -> None:
    stop = parse_router_command(":stop")
    explain = parse_router_command(":explain")
    assert stop is not None
    assert explain is not None

    assert transition_from("maturity", stop) is None
    assert transition_from("maturity", explain) == "maturity"


def test_narrative_line_contains_required_phase_marker() -> None:
    from mobius.v3a.phase_router.transitions import PHASES

    rendered = narrative_line(PHASES[1], "Generated spec.yaml v2.", next_phase=PHASES[2])

    assert "[Phase 2/4 complete — Seed]" in rendered
    assert "✓ Generated spec.yaml v2." in rendered
    assert "[Y / n / explain / back / stop]" in rendered


def test_latest_resume_point_uses_next_phase_after_latest_completed_event(tmp_path: Path) -> None:
    from mobius.persistence.event_store import EventStore
    from mobius.v3a.phase_router.resume import latest_resume_point

    with EventStore(tmp_path / "events.db") as store:
        store.append_event(
            "build-todo",
            "phase.completed",
            {"phase": "interview", "phase_index": 1, "fixture": "fixture.yaml"},
        )
        store.append_event(
            "build-todo",
            "phase.completed",
            {"phase": "seed", "phase_index": 2, "spec_yaml": "spec.yaml"},
        )

        resume_point = latest_resume_point(store)

    assert resume_point.run_id == "build-todo"
    assert resume_point.completed_phase == "seed"
    assert resume_point.next_phase == "maturity"
    assert resume_point.artifacts["spec_yaml"] == "spec.yaml"
