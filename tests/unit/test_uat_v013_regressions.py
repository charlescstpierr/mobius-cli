"""Regression tests for issues found in the v0.1.2 UAT report.

These tests pin the user-visible behaviors fixed in v0.1.3:

* Bug #1 - ``MOBIUS_HOME`` pointing at an unwritable path emits a friendly
  one-line error on stderr (no Python traceback) and exits with code 1.
* Bug #2 - ``mobius interview --non-interactive`` exits non-zero with a
  message on stderr when ``--input`` or ``--output`` is missing.
* Bug #3 - ``mobius config get event_store`` (and other derived path keys)
  returns the same value that ``mobius config show`` lists.
* UX  #4 - ``mobius setup`` actually installs at least one bundled asset on
  a fresh install instead of reporting "0 asset(s)".
* Docs #5 - README documents ``pip install <wheel-url>`` as a first-class
  install option.
* Docs #6 - ``mobius init`` prints the resolved MOBIUS_HOME, says how to
  override it, and the README explains the global event store.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mobius.cli.main import CliContext

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- Bug #1
def test_bad_mobius_home_emits_friendly_error_and_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read-only MOBIUS_HOME must not surface a Python traceback."""
    bogus = tmp_path / "no" / "permission"
    monkeypatch.setenv("MOBIUS_HOME", str(bogus))

    # Simulate a state-directory creation failure inside main().
    def boom(_argv: list[str]) -> bool:
        raise PermissionError(13, "Permission denied", str(bogus))

    cli_init = importlib.import_module("mobius.cli")
    monkeypatch.setattr(cli_init, "_try_fast_path", boom)
    monkeypatch.setattr(sys, "argv", ["mobius", "status"])
    # ``entry_point`` is a stable reference to the package-level main(); the
    # plain ``main`` attribute is shadowed by the cli.main submodule once it
    # has been imported during the same test session.
    main_fn = cli_init.entry_point
    assert callable(main_fn)

    with pytest.raises(SystemExit) as exit_info:
        main_fn()

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert "cannot create Mobius state directory" in captured.err
    assert str(bogus) in captured.err
    assert "MOBIUS_HOME" in captured.err


# --------------------------------------------------------------------------- Bug #2
def test_interview_non_interactive_missing_input_exits_nonzero() -> None:
    """`mobius interview --non-interactive` (no flags) must exit non-zero."""
    proc = subprocess.run(
        ["uv", "run", "mobius", "interview", "--non-interactive"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode != 0
    assert proc.stdout == ""
    assert "--input" in proc.stderr


def test_interview_non_interactive_defaults_output_to_cwd_spec_yaml(tmp_path: Path) -> None:
    """v0.1.4: --output is optional and defaults to ``./spec.yaml`` in cwd."""
    fixture = tmp_path / "f.yaml"
    fixture.write_text(
        "project_type: greenfield\n"
        "goal: Test exit code propagation.\n"
        "constraints:\n  - constraint with detail\n"
        "success:\n  - outcome with detail\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            "uv",
            "run",
            "mobius",
            "interview",
            "--non-interactive",
            "--input",
            str(fixture),
        ],
        cwd=str(tmp_path),  # run from tmp_path so spec.yaml lands here
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "spec.yaml").exists()


# --------------------------------------------------------------------------- Bug #3
def test_config_get_event_store_returns_derived_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_module = importlib.import_module("mobius.cli.commands.config")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)

    config_module.get(ctx, "event_store")
    captured = capsys.readouterr()

    assert captured.out.strip() == str(home / "events.db")
    assert captured.err == ""


def test_config_get_state_dir_and_config_file_match_show(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_module = importlib.import_module("mobius.cli.commands.config")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)

    for key, expected in (
        ("state_dir", str(home)),
        ("config_file", str(home / "config.json")),
    ):
        config_module.get(ctx, key)
        out = capsys.readouterr().out.strip()
        assert out == expected, f"{key} returned {out!r}, expected {expected!r}"


# --------------------------------------------------------------------------- UX #4
def test_setup_bundles_assets_inside_package() -> None:
    """The wheel must ship the SKILL.md / command markdown files it installs."""
    integration = importlib.import_module("mobius.integration")
    skills = integration.skills_root()
    commands = integration.claude_commands_root()
    skill_names = {entry.name for entry in skills.iterdir() if entry.is_dir()}
    command_names = {entry.name for entry in commands.iterdir() if entry.is_file()}
    expected = {"cancel", "evolve", "help", "interview", "run", "seed", "setup", "status", "qa"}
    assert expected.issubset(skill_names)
    assert {f"{name}.md" for name in expected}.issubset(command_names)


def test_setup_claude_installs_at_least_one_asset_on_fresh_install(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "MOBIUS_TEST_HOME": str(tmp_path),
        "NO_COLOR": "1",
    }
    proc = subprocess.run(
        ["uv", "run", "mobius", "setup", "--runtime", "claude"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    # Reject the previous "0 asset(s)" path by asserting at least one install line.
    assert "install:" in proc.stdout
    # Summary must report a non-zero count and split planned vs unchanged.
    assert "installed" in proc.stdout
    assert "0 Mobius asset(s)" not in proc.stdout


# --------------------------------------------------------------------------- Docs #5
def test_readme_documents_pip_install_wheel_url() -> None:
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "pip install https://github.com/charlescstpierr/mobius-cli/releases" in text


# --------------------------------------------------------------------------- Docs #6
def test_init_output_documents_mobius_home_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MOBIUS_HOME", raising=False)
    init_module = importlib.import_module("mobius.cli.commands.init")
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)

    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    init_module.run(ctx, workspace)
    out = buffer.getvalue()

    assert "mobius_home=" in out
    assert "MOBIUS_HOME not set" in out
    assert "shared across projects" in out
    assert "set MOBIUS_HOME per-project" in out


def test_init_output_acknowledges_explicit_mobius_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOBIUS_HOME", str(tmp_path / "explicit"))
    init_module = importlib.import_module("mobius.cli.commands.init")
    workspace = tmp_path / "ws"
    home = tmp_path / "explicit"
    ctx = CliContext(json_output=False, mobius_home=home)

    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    init_module.run(ctx, workspace)
    out = buffer.getvalue()

    assert "MOBIUS_HOME from environment" in out


def test_readme_documents_mobius_home_default_path() -> None:
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "MOBIUS_HOME" in text
    assert "~/.mobius/events.db" in text
    assert "shared across every Mobius project" in text
