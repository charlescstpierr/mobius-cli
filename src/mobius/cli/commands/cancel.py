"""Handler for the Mobius cancel command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.cancel import CancelResult, cancel_run


def run(context: CliContext, run_id: str, *, grace_period: float = 10.0) -> None:
    """Cancel a detached run by PID file."""
    result = cancel_run(get_paths(context.mobius_home), run_id, grace_period=grace_period)
    if result is CancelResult.NOT_FOUND:
        output.write_error_line(f"run not found: {run_id}")
        raise typer.Exit(code=int(ExitCode.NOT_FOUND))
    if result is CancelResult.ALREADY_FINISHED:
        output.write_line(f"already finished {run_id}")
        return
    output.write_line(f"cancelled {run_id}")
