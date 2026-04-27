#!/usr/bin/env python3
"""Accept a hook envelope and return an empty action payload."""

from __future__ import annotations

import json
import sys
from contextlib import suppress


def main() -> int:
    """Consume stdin so agent runtimes can call this hook safely."""
    with suppress(json.JSONDecodeError):
        json.loads(sys.stdin.read() or "{}")
    sys.stdout.write("{}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
