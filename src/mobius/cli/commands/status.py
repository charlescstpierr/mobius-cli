"""Stub handler for the Mobius status command."""

from __future__ import annotations

from mobius.cli import output
from mobius.cli.main import CliContext


def run(_context: CliContext) -> None:
    """Run the not-yet-implemented status command."""
    output.write_line("not implemented")
