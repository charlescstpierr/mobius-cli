"""Handler for the Mobius repair command."""

from __future__ import annotations

import json

import typer

from mobius.cli import output
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
    if context.json_output or json_output:
        output.write_json(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    elif actions:
        for action in actions:
            output.write_line(
                f"{action.repair_type}: {action.target} — {action.before} -> {action.after}"
            )
    else:
        output.write_line("no repairs needed")

    raise typer.Exit(code=int(ExitCode.OK))
