"""Fuzz coverage for the custom seed-spec parser."""

from __future__ import annotations

import random
import string

from mobius.workflow.seed import SpecParseError, _parse_mapping


def _random_line(rng: random.Random) -> str:
    prefixes = ["", "  ", "    ", "      ", "        ", "- ", "  - ", "---", "# "]
    tokens = [
        "goal",
        "constraints",
        "success_criteria",
        "metadata",
        "owner",
        "agent_instructions",
        ":",
        "-",
        "&anchor",
        "*ref",
        "!!str",
        "|",
        ">",
        "{",
        "}",
        "[",
        "]",
        '"quoted: value"',
    ]
    if rng.random() < 0.35:
        body = "".join(rng.choice(string.printable[:90]) for _ in range(rng.randint(0, 40)))
    else:
        body = " ".join(rng.choice(tokens) for _ in range(rng.randint(1, 5)))
    return f"{rng.choice(prefixes)}{body}"


def test_fuzz_no_uncontrolled_crash() -> None:
    rng = random.Random(20260428)

    for _ in range(1000):
        raw = "\n".join(_random_line(rng) for _ in range(rng.randint(1, 20)))
        try:
            _parse_mapping(raw)
        except Exception as exc:  # noqa: BLE001 - fuzz target checks exception boundary.
            assert isinstance(exc, SpecParseError), f"unexpected {type(exc).__name__}: {exc}"
