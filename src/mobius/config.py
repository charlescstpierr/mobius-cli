"""Mobius configuration and XDG-style runtime paths."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mobius.persistence.event_store import EventStore

_STATE_DIR_MODE = 0o700
_CONFIG_FILE_MODE = 0o600
_DEFAULT_PROFILE = "dev"
_DEFAULT_LOG_LEVEL = "info"


@dataclass(frozen=True)
class MobiusPaths:
    """Resolved filesystem locations for Mobius state."""

    home: Path
    state_dir: Path
    event_store: Path
    config_file: Path


@dataclass(frozen=True)
class MobiusConfig:
    """User-editable Mobius configuration."""

    profile: str = _DEFAULT_PROFILE
    log_level: str = _DEFAULT_LOG_LEVEL
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> MobiusConfig:
        """Build a config object from JSON-compatible data."""
        profile = str(values.get("profile", _DEFAULT_PROFILE))
        log_level = str(values.get("log_level", _DEFAULT_LOG_LEVEL))
        extra = {
            str(key): str(value)
            for key, value in values.items()
            if key not in {"profile", "log_level"}
        }
        return cls(profile=profile, log_level=log_level, extra=extra)

    def to_mapping(self) -> dict[str, str]:
        """Return a stable JSON-serializable mapping."""
        return {
            "profile": self.profile,
            "log_level": self.log_level,
            **dict(sorted(self.extra.items())),
        }

    def get_value(self, key: str) -> str | None:
        """Return a config value by key, or None if it is unknown."""
        if key == "profile":
            return self.profile
        if key == "log_level":
            return self.log_level
        return self.extra.get(key)

    def with_value(self, key: str, value: str) -> MobiusConfig:
        """Return a copy with one key set."""
        if key == "profile":
            return MobiusConfig(profile=value, log_level=self.log_level, extra=dict(self.extra))
        if key == "log_level":
            return MobiusConfig(profile=self.profile, log_level=value, extra=dict(self.extra))
        extra = dict(self.extra)
        extra[key] = value
        return MobiusConfig(profile=self.profile, log_level=self.log_level, extra=extra)


@dataclass(frozen=True)
class LoadedConfig:
    """Configuration loaded alongside the paths that produced it."""

    paths: MobiusPaths
    config: MobiusConfig


def default_home() -> Path:
    """Return the configured Mobius home directory."""
    configured_home = os.environ.get("MOBIUS_HOME")
    return Path(configured_home).expanduser() if configured_home else Path.home() / ".mobius"


def get_paths(home: str | Path | None = None) -> MobiusPaths:
    """Resolve Mobius paths under ``home`` or ``$MOBIUS_HOME``/``~/.mobius``."""
    resolved_home = Path(home).expanduser() if home is not None else default_home()
    return MobiusPaths(
        home=resolved_home,
        state_dir=resolved_home,
        event_store=resolved_home / "events.db",
        config_file=resolved_home / "config.json",
    )


def load_config(home: str | Path | None = None) -> LoadedConfig:
    """Load config, creating the state directory and event store on first use."""
    paths = get_paths(home)
    _ensure_state(paths)
    if paths.config_file.exists():
        values = json.loads(paths.config_file.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            msg = f"config file must contain a JSON object: {paths.config_file}"
            raise ValueError(msg)
        config = MobiusConfig.from_mapping(values)
    else:
        config = MobiusConfig()
        _write_config(paths.config_file, config)
    return LoadedConfig(paths=paths, config=config)


def save_config(home: str | Path | None, key: str, value: str) -> MobiusConfig:
    """Set a config value and persist it idempotently."""
    loaded = load_config(home)
    updated = loaded.config.with_value(key, value)
    if updated != loaded.config:
        _write_config(loaded.paths.config_file, updated)
    return updated


def _ensure_state(paths: MobiusPaths) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=_STATE_DIR_MODE)
    os.chmod(paths.state_dir, _STATE_DIR_MODE)
    with EventStore(paths.event_store):
        pass


def _write_config(path: Path, config: MobiusConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=_STATE_DIR_MODE)
    os.chmod(path.parent, _STATE_DIR_MODE)
    payload = json.dumps(config.to_mapping(), sort_keys=True, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(f"{payload}\n")
    os.chmod(temp_path, _CONFIG_FILE_MODE)
    temp_path.replace(path)
    os.chmod(path, _CONFIG_FILE_MODE)
