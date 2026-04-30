"""Handlers for the Mobius evolve command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.evolve import (
    EvolutionSourceNotFoundError,
    execute_evolution,
    prepare_evolution,
    run_foreground,
    start_detached_worker,
)
from mobius.workflow.launcher import WorkerLauncher, evolution_worker_config


def run(
    context: CliContext,
    *,
    source_run_id: str,
    generations: int,
    detach: bool = True,
    foreground: bool = False,
) -> None:
    """Prepare and start an evolution loop."""
    paths = get_paths(context.mobius_home)
    try:
        prepared = prepare_evolution(paths, source_run_id, generations=generations)
    except EvolutionSourceNotFoundError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.NOT_FOUND)) from exc

    WorkerLauncher(paths).launch_for_cli(
        evolution_worker_config(
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


def worker_evolve(context: CliContext, *, evolution_id: str) -> None:
    """Execute a prepared evolution from the private ``_worker`` command."""
    paths = get_paths(context.mobius_home)
    exit_code = execute_evolution(paths, evolution_id, stream_events=True)
    if exit_code != int(ExitCode.OK):
        raise typer.Exit(code=exit_code)
