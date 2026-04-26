import importlib
import signal
import sys

import pytest
import typer
from typer.testing import CliRunner


def test_structured_exit_codes_are_declared() -> None:
    main = importlib.import_module("mobius.cli.main")

    assert int(main.ExitCode.OK) == 0
    assert int(main.ExitCode.GENERIC_ERROR) == 1
    assert int(main.ExitCode.USAGE) == 2
    assert int(main.ExitCode.VALIDATION) == 3
    assert int(main.ExitCode.NOT_FOUND) == 4
    assert int(main.ExitCode.INTERRUPTED) == 130


def test_sigint_handler_exits_130() -> None:
    main = importlib.import_module("mobius.cli.main")

    with pytest.raises(typer.Exit) as exc_info:
        main._handle_sigint(signal.SIGINT, None)  # noqa: SLF001

    assert exc_info.value.exit_code == 130


def test_handler_modules_are_not_imported_for_help() -> None:
    main = importlib.import_module("mobius.cli.main")
    command_modules = [
        "mobius.cli.commands.interview",
        "mobius.cli.commands.seed",
        "mobius.cli.commands.run",
        "mobius.cli.commands.status",
        "mobius.cli.commands.ac_tree",
        "mobius.cli.commands.qa",
        "mobius.cli.commands.cancel",
        "mobius.cli.commands.evolve",
        "mobius.cli.commands.lineage",
        "mobius.cli.commands.setup",
        "mobius.cli.commands.config",
    ]

    for module_name in command_modules:
        sys.modules.pop(module_name, None)

    result = CliRunner().invoke(main.app, ["--help"])

    assert result.exit_code == 0
    for module_name in command_modules:
        assert module_name not in sys.modules


def test_handler_module_imports_only_when_subcommand_is_invoked() -> None:
    main = importlib.import_module("mobius.cli.main")
    sys.modules.pop("mobius.cli.commands.status", None)

    result = CliRunner().invoke(main.app, ["status"])

    assert result.exit_code == 0
    assert "not implemented" in result.stdout
    assert "mobius.cli.commands.status" in sys.modules
