"""Handler for the Mobius doctor command."""

from __future__ import annotations

import typer

from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode


def run(
    context: CliContext,
    *,
    json_output: bool = False,
) -> None:
    """Run environment diagnostics and emit text or JSON results."""
    from pathlib import Path

    from mobius.workflow.doctor import run_doctor

    checks = run_doctor(cwd=Path.cwd(), mobius_home=context.mobius_home)
    payload = [check.to_payload() for check in checks]
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(
        payload,
        text=[f"{check.check_name}: {check.status} — {check.details}" for check in checks],
    )

    if any(check.status == "fail" for check in checks):
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))
    raise typer.Exit(code=int(ExitCode.OK))
