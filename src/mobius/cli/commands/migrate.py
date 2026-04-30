"""Handler for the Mobius migrate command."""

from __future__ import annotations

from pathlib import Path

import typer

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode


def run(
    context: CliContext,
    spec_path: Path,
    *,
    json_output: bool = False,
) -> None:
    """Migrate a v1 spec.yaml file to spec v2."""
    from mobius.workflow.migrate import migrate_spec

    try:
        result = migrate_spec(spec_path)
    except FileNotFoundError as exc:
        output.write_error_line(f"spec file not found: {spec_path}")
        raise typer.Exit(code=int(ExitCode.NOT_FOUND)) from exc
    except OSError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR)) from exc

    payload = result.to_payload()
    formatter = get_formatter(context, json_output=json_output)
    backup_note = "created" if result.backup_created else "preserved"
    text = (
        [
            f"migrated {result.spec_path} to spec_version: 2",
            f"backup {backup_note}: {result.backup_path}",
        ]
        if result.changed
        else f"already spec_version: 2: {result.spec_path}"
    )
    formatter.emit(payload, text=text)

    raise typer.Exit(code=int(ExitCode.OK))
