"""Mobius Typer CLI entry point with lazy subcommand loading."""

from __future__ import annotations

import importlib
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Annotated, Protocol, cast

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
    "interview": "mobius.cli.commands.interview",
    "seed": "mobius.cli.commands.seed",
    "run": "mobius.cli.commands.run",
    "status": "mobius.cli.commands.status",
    "ac-tree": "mobius.cli.commands.ac_tree",
    "qa": "mobius.cli.commands.qa",
    "cancel": "mobius.cli.commands.cancel",
    "evolve": "mobius.cli.commands.evolve",
    "lineage": "mobius.cli.commands.lineage",
    "setup": "mobius.cli.commands.setup",
    "config": "mobius.cli.commands.config",
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


def main() -> None:
    """Run the Mobius CLI."""
    app()
