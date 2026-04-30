from __future__ import annotations

from pathlib import Path


def test_full_build_ends_with_auto_handoff_menu_and_prompt_path(
    tmp_path: Path, mobius_runner
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = mobius_runner(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
        extra_env={"MOBIUS_V3A_WIZARD_COUNTDOWN": "0"},
        path_mode="bin_only",
    )

    assert result.returncode == 0, result.stderr
    assert "Mobius's job is done" in result.stdout
    assert "open in claude" in result.stdout
    assert "open in codex" in result.stdout
    assert "open in hermes" in result.stdout
    assert "quit" in result.stdout
    assert "handoff prompt path:" in result.stdout

    prompt_paths = list(workspace.glob(".mobius/build/*/handoff-prompt.md"))
    assert len(prompt_paths) == 1
    assert "tiny TODO CLI" in prompt_paths[0].read_text(encoding="utf-8")
