"""Rolling-window lemma novelty checks for Socrate rationales."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "because",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "must",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "turn",
        "we",
        "with",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class LemmaCheckResult:
    """Result of checking a Socrate ``because:`` field."""

    passed: bool
    new_lemmas: frozenset[str]
    current_lemmas: frozenset[str]
    previous_lemmas: frozenset[str]
    reason: str


def extract_lemmas(text: str) -> frozenset[str]:
    """Extract coarse deterministic lemmas from text."""
    lemmas: set[str] = set()
    for match in _WORD_RE.finditer(text.lower()):
        word = match.group(0).strip("_-")
        if len(word) < 3 or word in _STOPWORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = f"{word[:-3]}y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 4:
            word = word[:-1]
        lemmas.add(word)
    return frozenset(lemmas)


def rolling_window_lemmas(justifications: Iterable[str], *, window: int = 5) -> frozenset[str]:
    """Return all lemmas found in the last ``window`` justifications."""
    recent = list(justifications)[-window:]
    lemmas: set[str] = set()
    for justification in recent:
        lemmas.update(extract_lemmas(justification))
    return frozenset(lemmas)


def check_rolling_lemma(
    justification: str,
    previous_justifications: Iterable[str],
    *,
    window: int = 5,
    convergence_proposal: bool = False,
) -> LemmaCheckResult:
    """Require at least one lemma absent from the last five rationales.

    The convergence-proposing ``:done?`` turn is intentionally exempt so a
    small-vocabulary topic can stop instead of deadlocking.
    """
    current = extract_lemmas(justification)
    previous = rolling_window_lemmas(previous_justifications, window=window)
    new = current - previous
    if convergence_proposal:
        return LemmaCheckResult(True, new, current, previous, "convergence proposal exempt")
    if new:
        return LemmaCheckResult(True, new, current, previous, "novel lemma present")
    return LemmaCheckResult(False, new, current, previous, "no lemma outside rolling window")


class LemmaWindow:
    """Mutable rolling lemma state used by the interview loop."""

    def __init__(self, *, window: int = 5) -> None:
        self.window = window
        self._justifications: list[str] = []

    @property
    def justifications(self) -> tuple[str, ...]:
        """Return all accepted justifications."""
        return tuple(self._justifications)

    def check(self, justification: str, *, convergence_proposal: bool = False) -> LemmaCheckResult:
        """Check ``justification`` against the current rolling window."""
        return check_rolling_lemma(
            justification,
            self._justifications,
            window=self.window,
            convergence_proposal=convergence_proposal,
        )

    def accept(self, justification: str) -> None:
        """Record an accepted justification."""
        self._justifications.append(justification)
