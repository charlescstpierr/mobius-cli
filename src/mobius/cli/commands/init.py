"""Handler for the Mobius init command."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore

STARTER_SPEC_FILENAME = "spec.yaml"

STARTER_SPEC = """\
# Mobius starter spec — edit me before running `mobius run --spec spec.yaml`.
project_type: greenfield
goal: Describe what you want Mobius to build for you.
constraints:
  - Replace this constraint with a real one.
success_criteria:
  - Replace this criterion with something testable.
"""


def run(
    context: CliContext,
    target: Path,
    *,
    force: bool = False,
) -> None:
    """Scaffold a Mobius workspace at ``target``.

    Creates ``spec.yaml``, the MOBIUS_HOME state directory, and an initialized
    event store with WAL on. Idempotent: re-running on an existing workspace
    errors with exit 2 unless ``force`` is true.
    """
    workspace = target.expanduser().resolve()
    spec_path = workspace / STARTER_SPEC_FILENAME

    workspace.mkdir(parents=True, exist_ok=True)

    if spec_path.exists() and not force:
        sys.stderr.write(f"workspace already initialized: {spec_path} (use --force to overwrite)\n")
        raise typer.Exit(code=int(ExitCode.USAGE))

    spec_path.write_text(STARTER_SPEC, encoding="utf-8")

    paths = get_paths(context.mobius_home)
    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with EventStore(paths.event_store):
        pass

    sys.stdout.write(
        f"workspace={workspace}\n"
        f"spec={spec_path}\n"
        f"event_store={paths.event_store}\n"
        "next steps:\n"
        f"  edit {STARTER_SPEC_FILENAME} to describe your project\n"
        f"  mobius run --spec {STARTER_SPEC_FILENAME}\n"
        "  mobius status\n"
    )
