"""Handler for the Mobius repair command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode


def run(
    context: CliContext,
    *,
    json_output: bool = False,
) -> None:
    """Repair known environment issues and emit text or JSON results."""
    from pathlib import Path

    from mobius.workflow.repair import run_repair

    try:
        actions = run_repair(cwd=Path.cwd(), mobius_home=context.mobius_home)
    except OSError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR)) from exc

    payload = [action.to_payload() for action in actions]
    formatter = get_formatter(context, json_output=json_output)
    text = (
        [
            f"{action.repair_type}: {action.target} — {action.before} -> {action.after}"
            for action in actions
        ]
        if actions
        else "no repairs needed"
    )
    formatter.emit(payload, text=text)

    raise typer.Exit(code=int(ExitCode.OK))
