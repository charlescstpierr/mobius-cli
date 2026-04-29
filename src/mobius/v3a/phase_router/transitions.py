"""Deterministic transitions and prompts for the v3a phase router."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RouterCommand(Enum):
    """Universal phase-boundary commands accepted by the router."""

    NEXT = "next"
    BACK = "back"
    EXPLAIN = "explain"
    STOP = "stop"
    WHY = "why"


@dataclass(frozen=True)
class ParsedRouterCommand:
    """A parsed universal router command."""

    kind: RouterCommand
    count: int = 1


@dataclass(frozen=True)
class PhaseDefinition:
    """Static metadata for one build phase."""

    index: int
    key: str
    name: str
    next_key: str | None
    next_command: str
    explanation: str


PHASES: tuple[PhaseDefinition, ...] = (
    PhaseDefinition(
        index=1,
        key="interview",
        name="Interview",
        next_key="seed",
        next_command="mobius build",
        explanation="Socrate, Avocat, and Architecte clarify the intent into a v2 fixture.",
    ),
    PhaseDefinition(
        index=2,
        key="seed",
        name="Seed",
        next_key="maturity",
        next_command="mobius build",
        explanation="The v3a fixture is handed to v2's non-interactive interview writer.",
    ),
    PhaseDefinition(
        index=3,
        key="maturity",
        name="Maturity",
        next_key="scoring",
        next_command="mobius build",
        explanation="A deterministic readiness gate checks whether the spec is mature enough.",
    ),
    PhaseDefinition(
        index=4,
        key="scoring",
        name="Scoring + Delivery",
        next_key=None,
        next_command="mobius build complete",
        explanation="The build receives a /10 score and a delivery handoff.",
    ),
)

PHASE_BY_KEY: dict[str, PhaseDefinition] = {phase.key: phase for phase in PHASES}
PHASE_COUNT = len(PHASES)


def parse_router_command(value: str) -> ParsedRouterCommand | None:
    """Parse a universal phase-router command."""
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in {"y", "yes", "", ":next"}:
        return ParsedRouterCommand(RouterCommand.NEXT)
    if normalized in {"n", "no", ":stop"}:
        return ParsedRouterCommand(RouterCommand.STOP)
    if normalized == ":back":
        return ParsedRouterCommand(RouterCommand.BACK)
    if normalized.startswith(":back "):
        _, raw_count = normalized.split(maxsplit=1)
        try:
            count = int(raw_count)
        except ValueError:
            return None
        if count < 1:
            return None
        return ParsedRouterCommand(RouterCommand.BACK, count=count)
    if normalized == ":explain":
        return ParsedRouterCommand(RouterCommand.EXPLAIN)
    if normalized == ":why":
        return ParsedRouterCommand(RouterCommand.WHY)
    return None


def transition_from(
    current_phase_key: str,
    command: ParsedRouterCommand,
) -> str | None:
    """Return the next phase key for ``command`` from ``current_phase_key``."""
    current = PHASE_BY_KEY[current_phase_key]
    if command.kind is RouterCommand.NEXT:
        return current.next_key
    if command.kind is RouterCommand.BACK:
        target_index = max(1, current.index - command.count)
        return PHASES[target_index - 1].key
    if command.kind is RouterCommand.STOP:
        return None
    return current_phase_key


def narrative_line(
    phase: PhaseDefinition,
    summary: str,
    *,
    next_phase: PhaseDefinition | None = None,
) -> str:
    """Render the required post-phase narrative line."""
    if next_phase is None:
        next_text = "Next: Mobius build is complete."
    else:
        next_text = (
            f"Next: I will run {next_phase.name.lower()} "
            f"(Phase {next_phase.index}/{PHASE_COUNT})."
        )
    return (
        f"[Phase {phase.index}/{PHASE_COUNT} complete — {phase.name}]\n"
        f"✓ {summary}\n"
        f"{next_text}\n"
        "[Y / n / explain / back / stop]"
    )


def status_line(phase: PhaseDefinition, *, turn: int, ambiguity_score: float) -> str:
    """Render the v3a status line owned by the phase router."""
    return f"[Phase {phase.index}/{PHASE_COUNT} · turn {turn} · ambig {ambiguity_score:.2f}]"
