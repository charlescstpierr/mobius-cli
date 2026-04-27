"""Direct unit tests for the config command handler."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode


@pytest.fixture
def config_command() -> ModuleType:
    sys.modules.pop("mobius.cli.commands.config", None)
    return importlib.import_module("mobius.cli.commands.config")


def _ctx(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


def test_config_show_emits_key_value_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.show(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "state_dir=" in out
    assert "event_store=" in out
    assert "busy_timeout=" in out


def test_config_show_emits_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.show(_ctx(tmp_path), json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["busy_timeout"] == 30000
    assert "log_level" in payload


def test_config_get_unknown_key_exits_4(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    with pytest.raises(typer.Exit) as exc:
        config_command.get(_ctx(tmp_path), "nonexistent_key")
    assert exc.value.exit_code == int(ExitCode.NOT_FOUND)
    assert "not found" in capsys.readouterr().err


def test_config_get_known_key_emits_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    # set then get
    config_command.set_value(_ctx(tmp_path), "log_level", "debug")
    capsys.readouterr()
    config_command.get(_ctx(tmp_path), "log_level")
    out = capsys.readouterr().out.strip()
    assert out == "debug"


def test_config_get_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.set_value(_ctx(tmp_path), "log_level", "info")
    capsys.readouterr()
    config_command.get(_ctx(tmp_path), "log_level", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"key": "log_level", "value": "info"}


def test_config_set_emits_key_equals_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.set_value(_ctx(tmp_path), "log_level", "warn")
    out = capsys.readouterr().out.strip()
    assert out == "log_level=warn"


def test_config_set_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.set_value(_ctx(tmp_path), "log_level", "warn", json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"key": "log_level", "value": "warn"}


def test_config_run_defaults_to_show(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_command: ModuleType
) -> None:
    config_command.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "state_dir=" in out
