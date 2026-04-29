"""Mobius v3a extension surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__version__ = "0.1.5-v3a"


@dataclass(frozen=True)
class V3aRuntimeConfig:
    """Runtime paths used by v3a commands."""

    workspace: Path
    build_dir: Path


def load_runtime_config(workspace: Path | None = None) -> V3aRuntimeConfig:
    """Return the v3a runtime config for ``workspace``."""
    root = (workspace or Path.cwd()).expanduser().resolve()
    return V3aRuntimeConfig(workspace=root, build_dir=root / ".mobius" / "build")
