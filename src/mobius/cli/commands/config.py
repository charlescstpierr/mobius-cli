"""Handlers for the Mobius config command."""

from __future__ import annotations

import typer
from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import load_config, save_config


class ConfigShowOutput(BaseModel):
    """Structured config show output."""

    model_config = ConfigDict(extra="forbid")

    state_dir: str
    event_store: str
    config_file: str
    profile: str
    log_level: str
    values: dict[str, str]


class ConfigSetOutput(BaseModel):
    """Structured config set output."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


class ConfigGetOutput(BaseModel):
    """Structured config get output."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


def show(context: CliContext, *, json_output: bool = False) -> None:
    """Show resolved paths and persisted configuration."""
    loaded = load_config(context.mobius_home)
    payload = ConfigShowOutput(
        state_dir=str(loaded.paths.state_dir),
        event_store=str(loaded.paths.event_store),
        config_file=str(loaded.paths.config_file),
        profile=loaded.config.profile,
        log_level=loaded.config.log_level,
        values=loaded.config.to_mapping(),
    )
    if context.json_output or json_output:
        output.write_json(payload.model_dump_json())
        return

    output.write_line(f"state_dir={payload.state_dir}")
    output.write_line(f"event_store={payload.event_store}")
    output.write_line(f"config_file={payload.config_file}")
    for key, value in payload.values.items():
        output.write_line(f"{key}={value}")


def get(context: CliContext, key: str, *, json_output: bool = False) -> None:
    """Get one config value."""
    loaded = load_config(context.mobius_home)
    value = loaded.config.get_value(key)
    if value is None:
        output.write_error_line(f"config key not found: {key}")
        raise typer.Exit(code=int(ExitCode.NOT_FOUND))
    if context.json_output or json_output:
        output.write_json(ConfigGetOutput(key=key, value=value).model_dump_json())
        return
    output.write_line(value)


def set_value(context: CliContext, key: str, value: str, *, json_output: bool = False) -> None:
    """Set one config value idempotently."""
    config = save_config(context.mobius_home, key, value)
    persisted_value = config.get_value(key)
    if persisted_value is None:
        msg = f"failed to persist config key: {key}"
        raise RuntimeError(msg)
    if context.json_output or json_output:
        output.write_json(ConfigSetOutput(key=key, value=persisted_value).model_dump_json())
        return
    output.write_line(f"{key}={persisted_value}")


def run(_context: CliContext) -> None:
    """Default to showing config for backward-compatible `mobius config` use."""
    show(_context)
