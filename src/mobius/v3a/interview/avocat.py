"""Avocat edge-case injection agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AvocatStatement:
    """A hypothetical edge case stated without asking a question."""

    statement: str


_EDGE_CASES = (
    "Hypothetical: the user provides empty input and expects a clear error.",
    "Hypothetical: two users run the workflow concurrently on the same project.",
    "Hypothetical: a dependency is unavailable and the product must fail gracefully.",
    "Hypothetical: the smallest TODO list has one item and no metadata.",
)


def inject_edge_case(turn_index: int, intent: str) -> AvocatStatement:
    """Return a deterministic Avocat statement for this turn."""
    base = _EDGE_CASES[turn_index % len(_EDGE_CASES)]
    if "todo" in intent.lower():
        base = "Hypothetical: the TODO file is empty, duplicated, or contains one malformed item."
    return AvocatStatement(statement=base)
