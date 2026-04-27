#!/usr/bin/env python3
"""Suggest Mobius commands when an agent prompt uses the `ooo` shorthand."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

KEYWORD_PATTERN = re.compile(r"^ooo\s+(\S+)")


def detect_suggestion(envelope: dict[str, Any]) -> str | None:
    """Return a Mobius command suggestion for a supported prompt envelope."""
    prompt = envelope.get("prompt")
    if not isinstance(prompt, str):
        return None

    match = KEYWORD_PATTERN.match(prompt)
    if match is None:
        return None

    return f"mobius {match.group(1)}"


def main() -> int:
    """Read a JSON envelope from stdin and write a suggestion envelope to stdout."""
    try:
        envelope = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        envelope = {}

    if not isinstance(envelope, dict):
        envelope = {}

    suggestion = detect_suggestion(envelope)
    payload = {"suggestion": suggestion} if suggestion is not None else {}
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
