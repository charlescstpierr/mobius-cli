"""Architecte design option proposer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignOption:
    """One architecture option with a trade-off."""

    name: str
    trade_off: str


def propose_options(intent: str, turn_index: int) -> tuple[DesignOption, ...]:
    """Return one to three deterministic design options."""
    normalized = intent.lower()
    if "cli" in normalized or "todo" in normalized:
        options = (
            DesignOption("single-command CLI", "fast to ship, narrower extension surface"),
            DesignOption("subcommand CLI", "more structure, slightly more upfront design"),
            DesignOption("library plus CLI wrapper", "testable core, extra packaging surface"),
        )
    else:
        options = (
            DesignOption("thin vertical slice", "proves value early, leaves polish for later"),
            DesignOption("modular core", "clean boundaries, more initial scaffolding"),
            DesignOption("adapter-first shell", "easy integration, needs careful contracts"),
        )
    count = 1 + (turn_index % 3)
    return options[:count]
