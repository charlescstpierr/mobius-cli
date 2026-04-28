"""Handler for the Mobius handoff command."""

from __future__ import annotations

from pathlib import Path

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.handoff import generate_handoff
from mobius.workflow.seed import SeedSpecValidationError


def run(
    context: CliContext,
    *,
    agent: str,
    spec_path: Path,
    dry_run: bool,
) -> None:
    """Render and print a versioned handoff prompt."""
    paths = get_paths(context.mobius_home)
    try:
        rendered = generate_handoff(
            event_store_path=paths.event_store,
            spec_path=spec_path,
            agent=agent,
            dry_run=dry_run,
        )
    except SeedSpecValidationError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc
    except ValueError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.USAGE)) from exc

    output.write_line(rendered.prompt)
