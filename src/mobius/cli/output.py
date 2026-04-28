"""Dedicated stdout/stderr writers for CLI command data and user-facing errors."""

from __future__ import annotations

import os
import sys
from typing import Any


def _no_color() -> bool:
    return os.environ.get("NO_COLOR") is not None


def _console() -> type[Any]:
    from rich.console import Console

    return Console


def write_line(message: str) -> None:
    """Write one data line to stdout without terminal-width wrapping."""
    _console()(file=sys.stdout, no_color=_no_color(), soft_wrap=True).print(message)


def write_json(message: str) -> None:
    """Write one compact JSON payload to stdout."""
    sys.stdout.write(f"{message}\n")


def write_rich(renderable: Any, *, width: int | None = None) -> None:
    """Write a Rich renderable to stdout."""
    _console()(file=sys.stdout, no_color=_no_color(), soft_wrap=True, width=width).print(
        renderable
    )


def write_error_line(message: str) -> None:
    """Write one diagnostic line to stderr."""
    sys.stderr.write(f"{message}\n")
