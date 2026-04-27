"""Handlers for the Mobius run command."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.run import execute_run, prepare_run, run_foreground, start_detached_worker
from mobius.workflow.seed import SeedSpecValidationError


class RunOutput(BaseModel):
    """Structured output for a started run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: str
    pid: int | None
    log: str


def run(
    context: CliContext,
    *,
    spec_path: Path,
    detach: bool = True,
    foreground: bool = False,
) -> None:
    """Validate and start a run.

    Detach is the default: the command forks ``mobius _worker run <id>``, writes
    a PID file and immediately prints the run id. Foreground mode executes the
    same worker loop in-process and streams events to stderr.
    """
    if foreground and detach:
        detach = False

    paths = get_paths(context.mobius_home)
    try:
        prepared = prepare_run(paths, spec_path)
    except SeedSpecValidationError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc
    except OSError as exc:
        output.write_error_line(f"invalid spec: {exc}")
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc

    if foreground:
        exit_code = run_foreground(paths, prepared)
        if exit_code != int(ExitCode.OK):
            raise typer.Exit(code=exit_code)
        return

    if not detach:
        output.write_error_line("run requires either --detach or --foreground")
        raise typer.Exit(code=int(ExitCode.USAGE))

    pid = start_detached_worker(paths, prepared)
    payload = RunOutput(
        run_id=prepared.run_id,
        mode="detach",
        pid=pid,
        log=str(prepared.paths.log_file),
    )
    if context.json_output:
        output.write_json(payload.model_dump_json())
        return
    output.write_line(payload.run_id)


def worker_run(context: CliContext, *, run_id: str) -> None:
    """Execute a prepared run from the private ``_worker`` command."""
    paths = get_paths(context.mobius_home)
    exit_code = execute_run(paths, run_id, stream_events=True)
    if exit_code != int(ExitCode.OK):
        raise typer.Exit(code=exit_code)
