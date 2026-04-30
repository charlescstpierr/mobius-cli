"""Handlers for the Mobius run command."""

from __future__ import annotations

from pathlib import Path

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.launcher import WorkerLauncher, run_worker_config
from mobius.workflow.run import execute_run, prepare_run, run_foreground, start_detached_worker
from mobius.workflow.seed import SeedSpecValidationError


def run(
    context: CliContext, *, spec_path: Path, detach: bool = True, foreground: bool = False
) -> None:
    """Validate and start a run."""
    paths = get_paths(context.mobius_home)
    try:
        prepared = prepare_run(paths, spec_path)
    except SeedSpecValidationError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc
    except OSError as exc:
        output.write_error_line(f"invalid spec: {exc}")
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc

    WorkerLauncher(paths).launch_for_cli(
        run_worker_config(
            prepared,
            run_foreground=run_foreground,
            start_detached=start_detached_worker,
            success_exit_code=int(ExitCode.OK),
        ),
        detach=detach,
        foreground=foreground,
        json_output=context.json_output,
        usage_exit_code=int(ExitCode.USAGE),
    )


def worker_run(context: CliContext, *, run_id: str) -> None:
    """Execute a prepared run from the private ``_worker`` command."""
    paths = get_paths(context.mobius_home)
    exit_code = execute_run(paths, run_id, stream_events=True)
    if exit_code != int(ExitCode.OK):
        raise typer.Exit(code=exit_code)
