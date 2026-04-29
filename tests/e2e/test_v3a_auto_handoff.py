from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


def run_mobius_without_clipboard(
    *args: str,
    cwd: Path,
    mobius_home: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(MOBIUS_BIN), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MOBIUS_HOME": str(mobius_home),
            "MOBIUS_V3A_WIZARD_COUNTDOWN": "0",
            "NO_COLOR": "1",
            "PATH": str(MOBIUS_BIN.parent),
        },
    )


def test_full_build_ends_with_auto_handoff_menu_and_prompt_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = run_mobius_without_clipboard(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
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
