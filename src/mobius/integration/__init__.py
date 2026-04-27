"""Mobius integration assets shipped inside the wheel.

This package bundles the SKILL.md files and Claude command markdown files that
``mobius setup`` installs into agent runtimes. Bundling them inside the Python
package guarantees they are present regardless of how Mobius was installed
(uv, pipx, or ``pip install <wheel>``).
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable

ASSETS_PACKAGE = "mobius.integration.assets"


def assets_root() -> Traversable:
    """Return the bundled assets root as an importlib.resources Traversable."""
    return resources.files(ASSETS_PACKAGE)


def skills_root() -> Traversable:
    """Return the bundled skills directory."""
    return assets_root() / "skills"


def claude_commands_root() -> Traversable:
    """Return the bundled Claude slash-commands directory."""
    return assets_root() / "claude_commands"


__all__ = ["ASSETS_PACKAGE", "assets_root", "claude_commands_root", "skills_root"]
