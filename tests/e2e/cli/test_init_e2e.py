"""End-to-end tests for ``mobius init``."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_mobius(*args: str, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def test_init_scaffolds_workspace_with_spec_and_event_store(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    workspace = tmp_path / "workspace"

    result = run_mobius("init", str(workspace), mobius_home=mobius_home)

    assert result.returncode == 0, result.stderr
    spec_path = workspace / "spec.yaml"
    assert spec_path.exists()
    spec_text = spec_path.read_text(encoding="utf-8")
    assert "project_type:" in spec_text
    assert "goal:" in spec_text
    assert "constraints:" in spec_text
    assert "success_criteria:" in spec_text

    event_store = mobius_home / "events.db"
    assert event_store.exists()
    connection = sqlite3.connect(event_store)
    try:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert journal_mode.lower() == "wal"

    assert f"workspace={workspace.resolve()}" in result.stdout
    assert "next steps:" in result.stdout
    assert "mobius run --spec spec.yaml" in result.stdout
    assert "mobius status" in result.stdout
    assert result.stderr == ""


def test_init_default_target_is_current_directory(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    workspace = tmp_path / "cwd-workspace"
    workspace.mkdir()

    result = subprocess.run(
        ["uv", "run", "mobius", "init"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert (workspace / "spec.yaml").exists()


def test_init_is_idempotent_only_with_force(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    workspace = tmp_path / "workspace"

    first = run_mobius("init", str(workspace), mobius_home=mobius_home)
    assert first.returncode == 0
    spec_path = workspace / "spec.yaml"
    spec_path.write_text("custom: contents\n", encoding="utf-8")

    second = run_mobius("init", str(workspace), mobius_home=mobius_home)
    assert second.returncode == 2
    assert "already initialized" in second.stderr
    assert spec_path.read_text(encoding="utf-8") == "custom: contents\n"

    forced = run_mobius("init", str(workspace), "--force", mobius_home=mobius_home)
    assert forced.returncode == 0
    assert "project_type:" in spec_path.read_text(encoding="utf-8")
