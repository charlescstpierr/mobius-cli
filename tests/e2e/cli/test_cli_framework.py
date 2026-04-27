import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMANDS = [
    "interview",
    "seed",
    "run",
    "status",
    "ac-tree",
    "qa",
    "cancel",
    "evolve",
    "lineage",
    "setup",
    "config",
]


def run_mobius(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_help_lists_all_stub_commands_and_exits_zero() -> None:
    result = run_mobius("--help")

    assert result.returncode == 0
    for command in COMMANDS:
        assert command in result.stdout
    assert result.stderr == ""


def test_help_short_alias_works_for_root_and_subcommands() -> None:
    root = run_mobius("-h")
    assert root.returncode == 0
    assert "Usage:" in root.stdout

    for command in COMMANDS:
        result = run_mobius(command, "-h")
        assert result.returncode == 0
        assert "Usage:" in result.stdout


def test_version_prints_single_semver_line() -> None:
    result = run_mobius("--version")

    assert result.returncode == 0
    assert re.fullmatch(r"mobius \d+\.\d+\.\d+(\S*)?\n", result.stdout)
    assert result.stderr == ""


def test_stub_commands_print_not_implemented_and_exit_cleanly() -> None:
    for command in [
        command for command in COMMANDS if command not in {"config", "interview", "seed", "status"}
    ]:
        result = run_mobius(command)

        assert result.returncode == 0
        assert result.stdout == "not implemented\n"
        assert result.stderr == ""


def test_unknown_subcommand_exits_usage_error_with_empty_stdout() -> None:
    result = run_mobius("bogus-subcmd")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "No such command" in result.stderr


def test_no_color_disables_ansi_sequences_in_help() -> None:
    result = run_mobius("--help", env={"NO_COLOR": "1"})

    assert result.returncode == 0
    assert "\x1b[" not in result.stdout
    assert "\x1b[" not in result.stderr


def test_global_json_flag_is_accepted_before_subcommand() -> None:
    result = run_mobius("--json", "status")

    assert result.returncode == 0
    assert result.stdout.startswith('{"event_store":')


def test_mobius_home_override_is_available_to_cli_context(tmp_path: Path) -> None:
    script = (
        "from mobius.cli.main import build_context;"
        "import os;"
        "ctx=build_context(json_output=False);"
        "print(ctx.mobius_home)"
    )

    result = subprocess.run(
        ["uv", "run", sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(tmp_path)},
    )

    assert result.returncode == 0
    assert result.stdout.strip() == str(tmp_path)
