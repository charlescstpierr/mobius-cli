"""Handlers for the Mobius evolve command."""

from __future__ import annotations

import typer
from pydantic import BaseModel, ConfigDict

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


class EvolutionOutput(BaseModel):
    """Structured output for a started evolution."""

    model_config = ConfigDict(extra="forbid")

    evolution_id: str
    source_run_id: str
    mode: str
    generations: int
    pid: int | None
    log: str


def run(
    context: CliContext,
    *,
    source_run_id: str,
    generations: int,
    detach: bool = True,
    foreground: bool = False,
) -> None:
    """Prepare and start an evolution loop."""
    if foreground and detach:
        detach = False

    paths = get_paths(context.mobius_home)
    try:
        prepared = prepare_evolution(paths, source_run_id, generations=generations)
    except EvolutionSourceNotFoundError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.NOT_FOUND)) from exc

    if foreground:
        exit_code = run_foreground(paths, prepared)
        if exit_code != int(ExitCode.OK):
            raise typer.Exit(code=exit_code)
        return

    if not detach:
        output.write_error_line("evolve requires either --detach or --foreground")
        raise typer.Exit(code=int(ExitCode.USAGE))

    pid = start_detached_worker(paths, prepared)
    payload = EvolutionOutput(
        evolution_id=prepared.evolution_id,
        source_run_id=prepared.source_run_id,
        mode="detach",
        generations=prepared.generations,
        pid=pid,
        log=str(prepared.paths.log_file),
    )
    if context.json_output:
        output.write_json(payload.model_dump_json())
        return
    output.write_line(payload.evolution_id)


def worker_evolve(context: CliContext, *, evolution_id: str) -> None:
    """Execute a prepared evolution from the private ``_worker`` command."""
    paths = get_paths(context.mobius_home)
    exit_code = execute_evolution(paths, evolution_id, stream_events=True)
    if exit_code != int(ExitCode.OK):
        raise typer.Exit(code=exit_code)
