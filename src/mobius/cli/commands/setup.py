"""Stub handler for the Mobius setup command."""

from __future__ import annotations

from mobius.cli import output
from mobius.cli.main import CliContext


def run(_context: CliContext) -> None:
    """Run the not-yet-implemented setup command."""
    output.write_line("not implemented")
