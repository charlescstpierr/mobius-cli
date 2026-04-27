"""Mobius Typer CLI entry point with lazy subcommand loading."""

from __future__ import annotations

import importlib
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

import typer

from mobius import __version__
from mobius.cli import output
from mobius.logging import configure_logging


class ExitCode(IntEnum):
    """Documented Mobius process exit codes."""

    OK = 0
    GENERIC_ERROR = 1
    USAGE = 2
    VALIDATION = 3
    NOT_FOUND = 4
    INTERRUPTED = 130


@dataclass(frozen=True)
class CliContext:
    """Process-wide CLI options shared with lazily imported command handlers."""

    json_output: bool
    mobius_home: Path


class CommandModule(Protocol):
    """Protocol implemented by lazily imported command modules."""

    def run(self, context: CliContext) -> None:
        """Run the command with the shared CLI context."""


COMMAND_MODULES: dict[str, str] = {
    "setup": "mobius.cli.commands.setup",
}


app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    help="Fast, MCP-free workflow CLI.",
)


def build_context(*, json_output: bool) -> CliContext:
    """Build a lightweight CLI context from global flags and environment."""
    configured_home = os.environ.get("MOBIUS_HOME")
    mobius_home = Path(configured_home).expanduser() if configured_home else Path.home() / ".mobius"
    return CliContext(json_output=json_output, mobius_home=mobius_home)


def _version_callback(value: bool) -> None:
    if value:
        output.write_line(f"mobius {__version__}")
        raise typer.Exit(code=int(ExitCode.OK))


def _handle_sigint(_signum: int, _frame: object | None) -> None:
    output.write_error_line("interrupted")
    raise typer.Exit(code=int(ExitCode.INTERRUPTED))


@app.callback()
def cli(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON for commands that support structured output.",
        ),
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the Mobius version and exit.",
        ),
    ] = False,
) -> None:
    """Configure global CLI behavior."""
    signal.signal(signal.SIGINT, _handle_sigint)
    configure_logging(json_output=json_output)
    ctx.obj = build_context(json_output=json_output)


def _make_lazy_command(module_name: str) -> Callable[[typer.Context], None]:
    def command(ctx: typer.Context) -> None:
        module = importlib.import_module(module_name)
        cast(CommandModule, module).run(ctx.obj)

    return command


for command_name, module_name in COMMAND_MODULES.items():
    app.command(name=command_name, help="Stub command; implementation pending.")(
        _make_lazy_command(module_name)
    )


@app.command(name="cancel", help="Cancel a detached Mobius run.")
def cancel_command(
    ctx: typer.Context,
    run_id: Annotated[
        str,
        typer.Argument(help="Run id to cancel."),
    ],
    grace_period: Annotated[
        float,
        typer.Option(
            "--grace-period",
            min=0.0,
            help="Seconds to wait after SIGTERM before escalating to SIGKILL.",
        ),
    ] = 10.0,
) -> None:
    """Send SIGTERM to a detached worker and clean up its PID file."""
    module = importlib.import_module("mobius.cli.commands.cancel")
    cast(Any, module).run(ctx.obj, run_id, grace_period=grace_period)


@app.command(name="qa", help="Run deterministic QA checks for a Mobius run.")
def qa_command(
    ctx: typer.Context,
    run_id: Annotated[
        str,
        typer.Argument(help="Run id to judge."),
    ],
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Use deterministic local heuristics without any LLM or network calls.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON with summary and results.",
        ),
    ] = False,
) -> None:
    """Evaluate a run with the offline QA judge."""
    module = importlib.import_module("mobius.cli.commands.qa")
    cast(Any, module).run(
        ctx.obj,
        run_id,
        offline=offline,
        json_output=json_output,
    )


@app.command(name="run", help="Execute a Mobius seed spec.")
def run_command(
    ctx: typer.Context,
    spec_path: Annotated[
        Path,
        typer.Option(
            "--spec",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Seed spec file to execute.",
        ),
    ],
    detach: Annotated[
        bool,
        typer.Option(
            "--detach",
            help="Start a background worker and immediately print the run id.",
        ),
    ] = True,
    foreground: Annotated[
        bool,
        typer.Option(
            "--foreground",
            help="Run in the current process and stream events to stderr.",
        ),
    ] = False,
) -> None:
    """Validate a seed spec and execute it as a run."""
    module = importlib.import_module("mobius.cli.commands.run")
    cast(Any, module).run(
        ctx.obj,
        spec_path=spec_path,
        detach=detach,
        foreground=foreground,
    )


@app.command(name="evolve", help="Run a Mobius generation evolution loop.")
def evolve_command(
    ctx: typer.Context,
    source_run_id: Annotated[
        str,
        typer.Option(
            "--from",
            help="Completed run id to use as the evolution source.",
        ),
    ],
    generations: Annotated[
        int,
        typer.Option(
            "--generations",
            min=1,
            help="Maximum generation count (hard-capped at 30).",
        ),
    ] = 30,
    detach: Annotated[
        bool,
        typer.Option(
            "--detach",
            help="Start a background worker and immediately print the evolution id.",
        ),
    ] = True,
    foreground: Annotated[
        bool,
        typer.Option(
            "--foreground",
            help="Run in the current process and stream generation events to stderr.",
        ),
    ] = False,
) -> None:
    """Start a detached evolution by default."""
    module = importlib.import_module("mobius.cli.commands.evolve")
    cast(Any, module).run(
        ctx.obj,
        source_run_id=source_run_id,
        generations=generations,
        detach=detach,
        foreground=foreground,
    )


@app.command(name="lineage", help="Print an aggregate lineage tree or replay hash.")
def lineage_command(
    ctx: typer.Context,
    aggregate_id: Annotated[
        str | None,
        typer.Argument(help="Aggregate id to inspect."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON with ancestors[] and descendants[].",
        ),
    ] = False,
    hash_output: Annotated[
        bool,
        typer.Option(
            "--hash",
            help="Print the deterministic SHA-256 replay hash for the aggregate.",
        ),
    ] = False,
    aggregate: Annotated[
        str | None,
        typer.Option(
            "--aggregate",
            help="Aggregate id to hash or inspect; alias for the positional id.",
        ),
    ] = None,
) -> None:
    """Render lineage for a run/evolution aggregate."""
    module = importlib.import_module("mobius.cli.commands.lineage")
    cast(Any, module).run(
        ctx.obj,
        aggregate_id,
        aggregate=aggregate,
        json_output=json_output,
        hash_output=hash_output,
    )


@app.command(name="ac-tree", help="Print a compact acceptance-criteria tree for a run.")
def ac_tree_command(
    ctx: typer.Context,
    run_id: Annotated[
        str,
        typer.Argument(help="Run id to visualize."),
    ],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON with nodes[] and edges[].",
        ),
    ] = False,
    cursor: Annotated[
        int,
        typer.Option(
            "--cursor",
            min=0,
            help="Only include event delta nodes after this event sequence.",
        ),
    ] = 0,
    max_nodes: Annotated[
        int,
        typer.Option(
            "--max-nodes",
            min=5,
            help="Maximum nodes to emit before adding a truncation marker.",
        ),
    ] = 50,
) -> None:
    """Render the run's compact AC tree."""
    module = importlib.import_module("mobius.cli.commands.ac_tree")
    cast(Any, module).run(
        ctx.obj,
        run_id,
        json_output=json_output,
        cursor=cursor,
        max_nodes=max_nodes,
    )


@app.command(name="seed", help="Create a seed session from a project spec or interview session.")
def seed_command(
    ctx: typer.Context,
    spec_or_session_id: Annotated[
        str,
        typer.Argument(help="Path to a project spec file, or an interview session id."),
    ],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ] = False,
) -> None:
    """Validate a project spec and persist seed events."""
    module = importlib.import_module("mobius.cli.commands.seed")
    cast(Any, module).run(ctx.obj, spec_or_session_id, json_output=json_output)


@app.command(name="interview", help="Run the project interview and produce a spec.")
def interview_command(
    ctx: typer.Context,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Read deterministic answers from --input instead of prompting or using an LLM.",
        ),
    ] = False,
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Fixture file containing deterministic interview answers.",
        ),
    ] = None,
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output",
            file_okay=True,
            dir_okay=False,
            writable=True,
            help="Path where the generated spec YAML should be written.",
        ),
    ] = None,
) -> None:
    """Run the deterministic interview command."""
    module = importlib.import_module("mobius.cli.commands.interview")
    cast(Any, module).run(
        ctx.obj,
        non_interactive=non_interactive,
        input_path=input_path,
        output_path=output_path,
    )


@app.command(name="status", help="Show Mobius event-store status.")
def status_command(
    ctx: typer.Context,
    run_id: Annotated[
        str | None,
        typer.Argument(help="Optional run id to inspect."),
    ] = None,
    read_only: Annotated[
        bool,
        typer.Option(
            "--read-only",
            help="Open the event store via SQLite mode=ro without writing WAL frames.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ] = False,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            help="Poll the event store every 200ms and stream run event deltas until terminal.",
        ),
    ] = False,
) -> None:
    """Open the event store and report a lightweight status snapshot."""
    module = importlib.import_module("mobius.cli.commands.status")
    cast(Any, module).run(
        ctx.obj,
        run_id,
        read_only=read_only,
        json_output=json_output,
        follow=follow,
    )


config_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    help="Show, get, and set Mobius configuration.",
)


def _load_config_command_module() -> object:
    return importlib.import_module("mobius.cli.commands.config")


@config_app.callback()
def config_callback(ctx: typer.Context) -> None:
    """Show config when no config subcommand is provided."""
    if ctx.invoked_subcommand is None:
        module = _load_config_command_module()
        cast(Any, module).show(ctx.obj)


@config_app.command(name="show")
def config_show(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ] = False,
) -> None:
    """Show resolved paths and all config values."""
    module = _load_config_command_module()
    cast(Any, module).show(ctx.obj, json_output=json_output)


@config_app.command(name="get")
def config_get(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Config key to read.")],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ] = False,
) -> None:
    """Read one config value."""
    module = _load_config_command_module()
    cast(Any, module).get(ctx.obj, key, json_output=json_output)


@config_app.command(name="set")
def config_set(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="Config key to persist.")],
    value: Annotated[str, typer.Argument(help="Config value to persist.")],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ] = False,
) -> None:
    """Set one config value idempotently."""
    module = _load_config_command_module()
    cast(Any, module).set_value(ctx.obj, key, value, json_output=json_output)


app.add_typer(config_app, name="config")


worker_app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Internal Mobius worker commands.",
)


@worker_app.command(name="run")
def worker_run_command(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Prepared run id to execute.")],
) -> None:
    """Execute a prepared run. Internal command, not part of the public CLI."""
    module = importlib.import_module("mobius.cli.commands.run")
    cast(Any, module).worker_run(ctx.obj, run_id=run_id)


@worker_app.command(name="evolve")
def worker_evolve_command(
    ctx: typer.Context,
    evolution_id: Annotated[str, typer.Argument(help="Prepared evolution id to execute.")],
) -> None:
    """Execute a prepared evolution. Internal command, not part of the public CLI."""
    module = importlib.import_module("mobius.cli.commands.evolve")
    cast(Any, module).worker_evolve(ctx.obj, evolution_id=evolution_id)


app.add_typer(worker_app, name="_worker", hidden=True)


def main() -> None:
    """Run the Mobius CLI."""
    app()
