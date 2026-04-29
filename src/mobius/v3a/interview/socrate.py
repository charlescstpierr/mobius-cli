"""Socrate interview agent and convergence rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mobius.v3a.interview.lemma_check import LemmaCheckResult, check_rolling_lemma


class Keystroke(StrEnum):
    """Universal keystrokes accepted by the v3a interview phase."""

    ENOUGH = "enough"
    BACK = "back"
    RESTART = "restart"
    FORK = "fork"
    WHY = "why"
    STOP = "stop"


@dataclass(frozen=True)
class ParsedKeystroke:
    """Parsed user command."""

    kind: Keystroke
    count: int | None = None


@dataclass(frozen=True)
class SocrateTurn:
    """One Socrate output."""

    question: str
    because: str
    proposes_done: bool = False
    lemma_check: LemmaCheckResult | None = None


_QUESTION_PLAN: tuple[tuple[str, str], ...] = (
    (
        "What exact user outcome should the product deliver first?",
        "outcome scope — first deliverable is underspecified",
    ),
    (
        "Which command, screen, or API surface is the primary entry point?",
        "surface contract — entrypoint behavior needs a named interface",
    ),
    (
        "What constraints must never be violated while building it?",
        "constraint boundary — invariants are not yet explicit",
    ),
    (
        "Which edge case would make the product feel broken if mishandled?",
        "edgecase failure — exceptional behavior needs a crisp answer",
    ),
    (
        "What verifiable success signal proves the implementation is done?",
        "verification proof — completion needs a testable signal",
    ),
    (
        "What input data or vocabulary should the first version support?",
        "vocabulary data — accepted input domain remains open",
    ),
    (
        "What should happen when the smallest valid example is supplied?",
        "minimal example — baseline happy path is not pinned",
    ),
)


def parse_keystroke(raw: str) -> ParsedKeystroke | None:
    """Parse v3a interview keystrokes, returning ``None`` for normal answers."""
    value = raw.strip()
    if not value.startswith(":"):
        return None
    parts = value[1:].split()
    if not parts:
        return None
    command = parts[0].lower()
    aliases = {
        "enough": Keystroke.ENOUGH,
        "back": Keystroke.BACK,
        "restart": Keystroke.RESTART,
        "fork": Keystroke.FORK,
        "why": Keystroke.WHY,
        "stop": Keystroke.STOP,
    }
    kind = aliases.get(command)
    if kind is None:
        return None
    count = None
    if kind is Keystroke.BACK and len(parts) > 1:
        try:
            count = max(1, int(parts[1]))
        except ValueError:
            count = 1
    return ParsedKeystroke(kind=kind, count=count)


def propose_question(
    turn_index: int,
    previous_justifications: list[str] | tuple[str, ...],
    *,
    convergence_ready: bool = False,
) -> SocrateTurn:
    """Return Socrate's next question while enforcing rolling lemma novelty."""
    if convergence_ready:
        because = ":done? convergence — ambiguity gate and component thresholds are satisfied"
        lemma = check_rolling_lemma(
            because,
            previous_justifications,
            convergence_proposal=True,
        )
        return SocrateTurn(
            question=":done? I think I understand. Stop now?",
            because=because,
            proposes_done=True,
            lemma_check=lemma,
        )

    for offset in range(len(_QUESTION_PLAN)):
        question, because = _QUESTION_PLAN[(turn_index + offset) % len(_QUESTION_PLAN)]
        lemma = check_rolling_lemma(because, previous_justifications)
        if lemma.passed:
            return SocrateTurn(question=question, because=because, lemma_check=lemma)
    fallback = f"novelty turn-{turn_index} — new detail needed to keep progress non-repetitive"
    lemma = check_rolling_lemma(fallback, previous_justifications)
    return SocrateTurn(
        question="What additional detail would remove the biggest remaining uncertainty?",
        because=fallback,
        lemma_check=lemma,
    )
