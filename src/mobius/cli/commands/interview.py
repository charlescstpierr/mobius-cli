"""Stub handler for the Mobius interview command."""

from __future__ import annotations

from mobius.cli import output
from mobius.cli.main import CliContext


def run(_context: CliContext) -> None:
    """Run the not-yet-implemented interview command."""
    output.write_line("not implemented")
