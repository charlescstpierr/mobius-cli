"""Unit tests for ``mobius init`` handler."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from mobius.cli.commands import init as init_command
from mobius.cli.main import CliContext
from mobius.workflow.seed import load_seed_spec


def _context(mobius_home: Path) -> CliContext:
    return CliContext(json_output=False, mobius_home=mobius_home)


def test_init_writes_spec_and_creates_event_store(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    mobius_home = tmp_path / "home"

    init_command.run(_context(mobius_home), workspace)

    spec_path = workspace / "spec.yaml"
    assert spec_path.exists()
    # Starter spec must be a valid seed spec the rest of the suite would accept
    # (after the user replaces the placeholder values, the keys are at minimum
    # well-formed). load_seed_spec validates structurally.
    spec = load_seed_spec(spec_path)
    assert spec.project_type == "greenfield"
    assert spec.goal
    assert spec.constraints
    assert spec.success_criteria
    assert (mobius_home / "events.db").exists()


def test_init_errors_with_exit_2_when_spec_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    mobius_home = tmp_path / "home"
    workspace.mkdir()
    (workspace / "spec.yaml").write_text("custom\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as exc_info:
        init_command.run(_context(mobius_home), workspace)

    assert int(exc_info.value.exit_code) == 2
    assert (workspace / "spec.yaml").read_text(encoding="utf-8") == "custom\n"


def test_init_force_overwrites_existing_spec(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    mobius_home = tmp_path / "home"
    workspace.mkdir()
    (workspace / "spec.yaml").write_text("custom\n", encoding="utf-8")

    init_command.run(_context(mobius_home), workspace, force=True)

    spec = load_seed_spec(workspace / "spec.yaml")
    assert spec.goal
