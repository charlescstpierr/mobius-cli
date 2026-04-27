"""Handler for the Mobius init command."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer

from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.templates import (
    TEMPLATE_NAMES,
    detect_template,
    get_template,
    render_spec,
)

STARTER_SPEC_FILENAME = "spec.yaml"


def run(
    context: CliContext,
    target: Path,
    *,
    force: bool = False,
    template: str | None = None,
) -> None:
    """Scaffold a Mobius workspace at ``target``.

    Creates ``spec.yaml`` (filled from a project-type template), the
    MOBIUS_HOME state directory, and an initialized event store with WAL
    on. Idempotent: re-running on an existing workspace errors with exit
    2 unless ``force`` is true.
    """
    workspace = target.expanduser().resolve()
    spec_path = workspace / STARTER_SPEC_FILENAME

    workspace.mkdir(parents=True, exist_ok=True)

    if spec_path.exists() and not force:
        sys.stderr.write(f"workspace already initialized: {spec_path} (use --force to overwrite)\n")
        raise typer.Exit(code=int(ExitCode.USAGE))

    if template is not None:
        template_key = template.strip().lower()
        if template_key not in TEMPLATE_NAMES:
            sys.stderr.write(
                f"unknown template: {template!r}. Valid options: {', '.join(TEMPLATE_NAMES)}\n"
            )
            raise typer.Exit(code=int(ExitCode.USAGE))
    else:
        template_key = detect_template(workspace)

    template_obj = get_template(template_key)
    spec_path.write_text(render_spec(template_obj), encoding="utf-8")

    paths = get_paths(context.mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with EventStore(paths.event_store):
        pass

    mobius_home = paths.home
    home_was_set = "MOBIUS_HOME" in os.environ
    home_note = (
        "MOBIUS_HOME from environment"
        if home_was_set
        else "MOBIUS_HOME not set; using default ~/.mobius (shared across projects)"
    )
    template_note = (
        f"# Template '{template_obj.name}' applied"
        f"{' (auto-detected)' if template is None else ''}: "
        f"{template_obj.description}"
    )
    sys.stdout.write(
        f"workspace={workspace}\n"
        f"spec={spec_path}\n"
        f"template={template_obj.name}\n"
        f"mobius_home={mobius_home}\n"
        f"event_store={paths.event_store}\n"
        f"{template_note}\n"
        f"# {home_note}\n"
        "# Tip: set MOBIUS_HOME per-project for an isolated event store, e.g.\n"
        f'#   export MOBIUS_HOME="{workspace}/.mobius"\n'
        "next steps:\n"
        f"  edit {STARTER_SPEC_FILENAME} to describe your project\n"
        f"  mobius run --spec {STARTER_SPEC_FILENAME}\n"
        "  mobius status\n"
    )
