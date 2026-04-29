from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


def run_mobius(
    *args: str,
    cwd: Path,
    mobius_home: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(MOBIUS_BIN), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
        env={
            **os.environ,
            "MOBIUS_HOME": str(mobius_home),
            "MOBIUS_V3A_WIZARD_COUNTDOWN": "0",
            "NO_COLOR": "1",
            "PATH": f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )


def count_events(db_path: Path, event_type: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM events WHERE type = ?",
            (event_type,),
        ).fetchone()
    finally:
        connection.close()
    return int(row[0])


def test_first_run_shows_tour_and_second_run_skips_in_same_project(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    first = run_mobius(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
        input_text="\n\n\n",
    )

    assert first.returncode == 0, first.stderr
    assert first.stdout.count("[first run detected — 60s tour]") == 3
    assert "Screen 1/3 — The 4-phase path" in first.stdout
    assert "Screen 2/3 — Phase 1 and 2" in first.stdout
    assert "Screen 3/3 — Phase 3 and 4" in first.stdout
    assert count_events(workspace / ".mobius" / "build" / "events.db", "human.tour_completed") == 1

    second = run_mobius(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
        input_text="\n\n\n",
    )

    assert second.returncode == 0, second.stderr
    assert "[first run detected — 60s tour]" not in second.stdout
    assert count_events(workspace / ".mobius" / "build" / "events.db", "human.tour_completed") == 1


def test_skip_tour_flag_bypasses_first_run_tour(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = run_mobius(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        "--skip-tour",
        cwd=workspace,
        mobius_home=tmp_path / "home",
        input_text="\n\n\n",
    )

    assert result.returncode == 0, result.stderr
    assert "[first run detected — 60s tour]" not in result.stdout
    assert count_events(workspace / ".mobius" / "build" / "events.db", "human.tour_completed") == 0
