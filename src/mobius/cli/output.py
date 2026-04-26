"""Dedicated stdout/stderr writers for CLI command data and user-facing errors."""

from __future__ import annotations

import os
import sys

from rich.console import Console


def _no_color() -> bool:
    return os.environ.get("NO_COLOR") is not None


def write_line(message: str) -> None:
    """Write one data line to stdout."""
    Console(file=sys.stdout, no_color=_no_color()).print(message)


def write_json(message: str) -> None:
    """Write one compact JSON payload to stdout."""
    sys.stdout.write(f"{message}\n")


def write_error_line(message: str) -> None:
    """Write one diagnostic line to stderr."""
    Console(file=sys.stderr, no_color=_no_color()).print(message)
