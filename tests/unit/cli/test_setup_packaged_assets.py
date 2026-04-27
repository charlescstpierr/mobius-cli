"""Tests for the packaged-asset fallback in mobius.cli.commands.setup.

In production, the wheel ships skill / command markdown under
``mobius.integration.assets``. Setup falls back to those bundled
resources when the source-tree directories (``PROJECT_ROOT/skills``,
``PROJECT_ROOT/.claude/commands``) are absent, e.g. for a ``pip install``
end-user invocation. These tests pin that fallback so it cannot regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mobius.cli.commands import setup as setup_command


def test_build_assets_uses_packaged_skills_when_source_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When SKILLS_SOURCE is missing, fall back to importlib.resources data."""
    monkeypatch.setattr(setup_command, "SKILLS_SOURCE", tmp_path / "missing-skills")
    monkeypatch.setattr(
        setup_command, "CLAUDE_COMMANDS_SOURCE", tmp_path / "missing-commands"
    )

    assets = setup_command._build_assets("claude", tmp_path / "out")
    targets = [str(a.target) for a in assets]

    # Skills must come from the packaged data root.
    assert any("/skills/setup/SKILL.md" in t for t in targets)
    assert any("/skills/run/SKILL.md" in t for t in targets)
    # Claude command markdown must also come from the packaged data.
    assert any("/commands/setup.md" in t for t in targets)
    assert any("/commands/run.md" in t for t in targets)
    # And the resolved sources must be readable file paths on disk.
    for asset in assets:
        assert asset.source.exists(), f"source not on disk: {asset.source}"


def test_build_assets_codex_uses_packaged_skills_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex/hermes runtimes must NOT install Claude command files."""
    monkeypatch.setattr(setup_command, "SKILLS_SOURCE", tmp_path / "missing-skills")
    monkeypatch.setattr(
        setup_command, "CLAUDE_COMMANDS_SOURCE", tmp_path / "missing-commands"
    )

    assets = setup_command._build_assets("codex", tmp_path / "out")
    targets = [str(a.target) for a in assets]

    assert any("/skills/" in t for t in targets)
    assert not any("/commands/" in t for t in targets)


def test_install_no_assets_prints_fallback_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty asset list emits the GitHub releases fallback note, no inventory."""
    inventory = tmp_path / "inv.json"
    setup_command._install(
        runtime="claude",
        scope="user",
        assets=[],
        inventory_path=inventory,
        dry_run=False,
    )

    out = capsys.readouterr().out
    assert "0 assets to install" in out
    assert "https://github.com/charlescstpierr/mobius-cli/releases" in out
    assert not inventory.exists()


def test_install_summary_reports_written_and_unchanged_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The summary line must split planned writes from unchanged skips."""
    monkeypatch.setattr(setup_command, "SKILLS_SOURCE", tmp_path / "missing-skills")
    monkeypatch.setattr(
        setup_command, "CLAUDE_COMMANDS_SOURCE", tmp_path / "missing-commands"
    )

    out_root = tmp_path / "out"
    inventory = tmp_path / "inv.json"
    assets = setup_command._build_assets("claude", out_root)
    setup_command._install(
        runtime="claude",
        scope="user",
        assets=assets,
        inventory_path=inventory,
        dry_run=False,
    )
    capsys.readouterr()

    setup_command._install(
        runtime="claude",
        scope="user",
        assets=assets,
        inventory_path=inventory,
        dry_run=False,
    )
    out = capsys.readouterr().out
    # Second run = idempotent: no new writes, all unchanged.
    assert "0 written" in out
    assert "unchanged" in out
    assert "skip:" in out
