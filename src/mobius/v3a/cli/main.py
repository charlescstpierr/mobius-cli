"""v3a Typer subcommand registration (kept separate from the v2 CLI core).

This module is imported by ``mobius.cli.main`` so that v3a commands live in
v3a-land and the core CLI does not hard-code v3a signatures.

All expensive imports happen inside the command callbacks, so importing this
module at CLI startup is lightweight.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

import typer

v3a_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="v3a-specific subcommands (matrix scoring, anti-regression diff).",
)

matrix_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Per-cell scoring and diff for the F10 anti-regression product matrix.",
)


def _commands_module() -> Any:
    """Import v3a command implementations only when a v3a command runs."""
    import importlib

    return importlib.import_module("mobius.v3a.cli.commands")


def build_command(
    ctx: typer.Context,
    intent: Annotated[
        str | None,
        typer.Argument(help="Product intent to clarify. Omit for interactive composer."),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Run with interactive prompts (default mode)."),
    ] = True,
    wizard: Annotated[
        bool,
        typer.Option(
            "--wizard",
            help="Auto-proceed through Phase 1 using deterministic answers.",
        ),
    ] = False,
    agent: Annotated[
        bool,
        typer.Option("--agent", help="Emit JSON suitable for coding-agent orchestration."),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from the next incomplete build phase."),
    ] = False,
    force_immature: Annotated[
        bool,
        typer.Option("--force-immature", help="Override the Phase 3 maturity gate."),
    ] = False,
    auto_top_up: Annotated[
        bool,
        typer.Option("--auto-top-up", help="Deterministically top up spec maturity."),
    ] = False,
    skip_tour: Annotated[
        bool,
        typer.Option("--skip-tour", help="Bypass the first-run guided tour."),
    ] = False,
    override_reason: Annotated[
        str | None,
        typer.Option("--override-reason", help="Reason recorded with --force-immature."),
    ] = None,
) -> None:
    """Run the v3a build command while keeping implementation under mobius.v3a."""
    module = _commands_module()
    cast(Any, module).run_build(
        ctx.obj,
        intent=intent,
        interactive=interactive,
        wizard=wizard,
        agent=agent,
        resume=resume,
        force_immature=force_immature,
        auto_top_up=auto_top_up,
        skip_tour=skip_tour,
        override_reason=override_reason,
    )


def maturity_command(
    ctx: typer.Context,
    spec: Annotated[
        Path,
        typer.Argument(help="Spec file to inspect."),
    ] = Path("spec.yaml"),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Run the read-only v3a maturity inspection command."""
    module = _commands_module()
    cast(Any, module).run_maturity(ctx.obj, spec=spec, json_output=json_output)


@matrix_app.command(name="score", help="Score every cell of a Spec's Product matrix.")
def matrix_score_command(
    ctx: typer.Context,
    spec: Annotated[
        Path,
        typer.Option(
            "--spec",
            help="Path to the Spec YAML/JSON file with a 'matrix:' block.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="Path where the canonical MatrixScores JSON will be written.",
        ),
    ],
) -> None:
    """Score every cell of a Spec's Product matrix into a canonical JSON file."""
    module = _commands_module()
    cast(Any, module).run_matrix_score(ctx.obj, spec=spec, output=output)


@matrix_app.command(name="diff", help="Compare two MatrixScores JSON files.")
def matrix_diff_command(
    ctx: typer.Context,
    baseline: Annotated[
        Path,
        typer.Option(
            "--baseline",
            help="Path to the baseline MatrixScores JSON file (schema_version=1).",
        ),
    ],
    candidate: Annotated[
        Path,
        typer.Option(
            "--candidate",
            help="Path to the candidate MatrixScores JSON file (schema_version=1).",
        ),
    ],
    tolerance: Annotated[
        int,
        typer.Option(
            "--tolerance",
            min=0,
            help="Maximum allowed per-cell drop before declaring a regression.",
        ),
    ] = 0,
) -> None:
    """Compare two MatrixScores JSON files and emit a verdict + exit code."""
    module = _commands_module()
    cast(Any, module).run_matrix_diff(
        ctx.obj,
        baseline=baseline,
        candidate=candidate,
        tolerance=tolerance,
    )


v3a_app.command(name="build", help="Run the v3a Interview Infinie build composer.")(
    build_command
)
v3a_app.command(name="maturity", help="Inspect the v3a deterministic maturity score.")(
    maturity_command
)
v3a_app.add_typer(matrix_app, name="matrix")


def register_top_level_commands(app: typer.Typer) -> None:
    """Register public v3a top-level aliases on the root Mobius app."""
    app.command(name="build", help="Run the v3a Interview Infinie build composer.")(
        build_command
    )
    app.command(name="maturity", help="Inspect the v3a deterministic maturity score.")(
        maturity_command
    )
