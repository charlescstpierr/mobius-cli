"""Install Mobius agent integration assets without registering MCP servers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.integration import claude_commands_root, skills_root

SUPPORTED_RUNTIMES = ("claude", "codex", "hermes")
SUPPORTED_SCOPES = ("user", "project")
PROJECT_ROOT = Path(__file__).resolve().parents[4]
# Source-tree fallbacks (used during `uv run` development); the canonical
# source is the package data shipped inside the wheel via mobius.integration.
SKILLS_SOURCE = PROJECT_ROOT / "skills"
CLAUDE_COMMANDS_SOURCE = PROJECT_ROOT / ".claude" / "commands"
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class Asset:
    """One source file destined for an agent runtime location."""

    source: Path
    target: Path


def run(
    _context: CliContext,
    *,
    runtime: str,
    scope: str = "user",
    dry_run: bool = False,
    uninstall: bool = False,
) -> None:
    """Install or remove Mobius agent integration assets."""
    runtime = runtime.lower()
    scope = scope.lower()
    _validate_runtime(runtime)
    _validate_scope(scope)

    root = _target_root(runtime, scope)
    inventory_path = _inventory_path(runtime, scope)

    if uninstall:
        _uninstall(runtime=runtime, scope=scope, inventory_path=inventory_path, dry_run=dry_run)
        return

    assets = _build_assets(runtime, root)
    _install(
        runtime=runtime,
        scope=scope,
        assets=assets,
        inventory_path=inventory_path,
        dry_run=dry_run,
    )


def _validate_runtime(runtime: str) -> None:
    if runtime not in SUPPORTED_RUNTIMES:
        output.write_error_line(
            f"unknown runtime '{runtime}'. Supported runtimes: {', '.join(SUPPORTED_RUNTIMES)}"
        )
        raise typer.Exit(code=int(ExitCode.USAGE))


def _validate_scope(scope: str) -> None:
    if scope not in SUPPORTED_SCOPES:
        output.write_error_line(
            f"unknown scope '{scope}'. Supported scopes: {', '.join(SUPPORTED_SCOPES)}"
        )
        raise typer.Exit(code=int(ExitCode.USAGE))


def _home() -> Path:
    """Return the home directory for integration writes.

    Tests set ``MOBIUS_TEST_HOME`` so e2e setup runs never touch the real user home.
    """
    configured = os.environ.get("MOBIUS_TEST_HOME")
    return Path(configured).expanduser() if configured else Path.home()


def _target_root(runtime: str, scope: str) -> Path:
    base = _home() if scope == "user" else Path.cwd()
    return base / f".{runtime}"


def _inventory_path(runtime: str, scope: str) -> Path:
    base = _home() if scope == "user" else Path.cwd()
    return base / ".mobius" / "installs" / f"{runtime}-{scope}.json"


def _build_assets(runtime: str, root: Path) -> list[Asset]:
    """Resolve assets from the source tree if present, else the packaged wheel data."""
    assets: list[Asset] = []
    skills_dir = SKILLS_SOURCE if SKILLS_SOURCE.is_dir() else None
    if skills_dir is not None:
        for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
            skill_name = skill_file.parent.name
            assets.append(Asset(skill_file, root / "skills" / skill_name / "SKILL.md"))
    else:
        bundled_skills = skills_root()
        for skill_dir in sorted(_iter_packaged_dirs(bundled_skills), key=lambda t: t.name):
            packaged_skill = skill_dir / "SKILL.md"
            if packaged_skill.is_file():
                target = root / "skills" / skill_dir.name / "SKILL.md"
                assets.append(Asset(_traversable_to_path(packaged_skill), target))

    # Each runtime gets the slash-command/prompt files in its conventional
    # location:
    #   - Claude Code  → ~/.claude/commands/<name>.md
    #   - Codex        → ~/.codex/prompts/<name>.md
    #   - Hermes       → ~/.hermes/commands/<name>.md
    # We reuse the same Markdown bodies; the shipping directory differs only
    # to match each agent's discovery convention.
    prompt_subdir = {
        "claude": "commands",
        "codex": "prompts",
        "hermes": "commands",
    }[runtime]

    commands_dir = CLAUDE_COMMANDS_SOURCE if CLAUDE_COMMANDS_SOURCE.is_dir() else None
    if commands_dir is not None:
        for command_file in sorted(commands_dir.glob("*.md")):
            assets.append(Asset(command_file, root / prompt_subdir / command_file.name))
    else:
        bundled_commands = claude_commands_root()
        for entry in sorted(_iter_packaged_files(bundled_commands), key=lambda t: t.name):
            if entry.name.endswith(".md"):
                assets.append(
                    Asset(_traversable_to_path(entry), root / prompt_subdir / entry.name)
                )

    return assets


def _iter_packaged_dirs(root: Traversable) -> list[Traversable]:
    return [entry for entry in root.iterdir() if entry.is_dir()]


def _iter_packaged_files(root: Traversable) -> list[Traversable]:
    return [entry for entry in root.iterdir() if entry.is_file()]


def _traversable_to_path(entry: Traversable) -> Path:
    """Materialize a package-resource Traversable to a real filesystem path.

    Inside a wheel/zip this writes to a short-lived temp file; for a regular
    site-packages install ``Path(...)`` already works.
    """
    try:
        return Path(str(entry))
    except TypeError:  # pragma: no cover - defensive for exotic loaders
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".asset") as file:
            file.write(entry.read_bytes())
            return Path(file.name)


def _install(
    *,
    runtime: str,
    scope: str,
    assets: list[Asset],
    inventory_path: Path,
    dry_run: bool,
) -> None:
    if not assets:
        output.write_line(
            f"setup found 0 assets to install for {runtime} ({scope}). "
            "This means the Mobius wheel was built without bundled skills/commands; "
            "reinstall a release wheel from "
            "https://github.com/charlescstpierr/mobius-cli/releases."
        )
        return

    entries: list[dict[str, str]] = []
    planned = 0
    skipped = 0

    for asset in assets:
        source_hash = _sha256(asset.source)
        entries.append({"path": str(asset.target), "sha256": source_hash})
        action = _install_action(asset, source_hash)
        if action == "skip":
            skipped += 1
        else:
            planned += 1
        output.write_line(f"{'would ' if dry_run else ''}{action}: {asset.target}")
        if not dry_run and action != "skip":
            _copy_if_changed(asset.source, asset.target, source_hash)

    if dry_run:
        output.write_line(
            f"dry-run: {planned} change(s) planned for {runtime} ({scope}); no filesystem writes"
        )
        return

    _write_inventory(inventory_path, runtime=runtime, scope=scope, entries=entries)
    summary = (
        f"installed {len(entries)} Mobius asset(s) for {runtime} ({scope}) "
        f"({planned} written, {skipped} unchanged)"
    )
    output.write_line(summary)


def _install_action(asset: Asset, source_hash: str) -> str:
    if not asset.target.exists():
        return "install"
    if _sha256(asset.target) == source_hash:
        return "skip"
    return "update"


def _copy_if_changed(source: Path, target: Path, source_hash: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha256(target) == source_hash:
        return
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(source.read_bytes())
    shutil.copymode(source, temp_path)
    temp_path.replace(target)


def _write_inventory(
    inventory_path: Path,
    *,
    runtime: str,
    scope: str,
    entries: list[dict[str, str]],
) -> None:
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": MANIFEST_VERSION,
        "runtime": runtime,
        "scope": scope,
        "assets": entries,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=inventory_path.parent,
        prefix=f".{inventory_path.name}.",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(f"{text}\n")
    temp_path.replace(inventory_path)


def _uninstall(*, runtime: str, scope: str, inventory_path: Path, dry_run: bool) -> None:
    inventory = _read_inventory(inventory_path)
    if inventory is None:
        output.write_line(
            f"{'would ' if dry_run else ''}remove: no Mobius inventory found "
            f"for {runtime} ({scope})"
        )
        return

    removed = 0
    assets = cast(list[object], inventory.get("assets", []))
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        hash_value = entry.get("sha256")
        if not isinstance(path_value, str) or not isinstance(hash_value, str):
            continue
        path = Path(path_value)
        if not path.exists():
            output.write_line(f"{'would ' if dry_run else ''}skip missing: {path}")
            continue
        if _sha256(path) != hash_value:
            output.write_line(f"{'would ' if dry_run else ''}skip modified: {path}")
            continue
        removed += 1
        output.write_line(f"{'would ' if dry_run else ''}remove: {path}")
        if not dry_run:
            path.unlink()
            _remove_empty_parents(path.parent, stop_at=_target_root(runtime, scope).parent)

    if dry_run:
        output.write_line(
            f"dry-run: {removed} removal(s) planned for {runtime} ({scope}); no filesystem writes"
        )
        return

    inventory_path.unlink(missing_ok=True)
    _remove_empty_parents(inventory_path.parent, stop_at=inventory_path.parents[2])
    output.write_line(f"removed {removed} Mobius asset(s) for {runtime} ({scope})")


def _read_inventory(inventory_path: Path) -> dict[str, object] | None:
    if not inventory_path.exists():
        return None
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path
    while current != stop_at and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
