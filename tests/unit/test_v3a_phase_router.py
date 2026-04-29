from __future__ import annotations

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


def test_phase_router_back_count_moves_to_prior_phase() -> None:
    command = parse_router_command(":back 2")
    assert command is not None

    assert transition_from("scoring", command) == "seed"


def test_narrative_line_contains_required_phase_marker() -> None:
    from mobius.v3a.phase_router.transitions import PHASES

    rendered = narrative_line(PHASES[1], "Generated spec.yaml v2.", next_phase=PHASES[2])

    assert "[Phase 2/4 complete — Seed]" in rendered
    assert "✓ Generated spec.yaml v2." in rendered
    assert "[Y / n / explain / back / stop]" in rendered
