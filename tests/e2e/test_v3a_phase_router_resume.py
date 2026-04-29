from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mobius.persistence.event_store import EventStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


def run_mobius(*args: str, cwd: Path, mobius_home: Path) -> subprocess.CompletedProcess[str]:
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
            "PATH": f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )


def seed_completed_phases(workspace: Path, *phases: str) -> None:
    (workspace / "spec.yaml").write_text(
        "\n".join(
            [
                "spec_version: 2",
                "project_type: greenfield",
                "goal: Ship a deterministic tiny TODO CLI.",
                "constraints:",
                "  - deterministic TODO behavior",
                "success_criteria:",
                "  - Happy path: user creates a TODO item.",
                "  - Edge case: invalid TODO input reports an error.",
                "verification_commands:",
                "  - command: uv run pytest -q",
                "    criterion_ref: 1",
                "    timeout_s: 60",
                "    shell: true",
                "  - command: uv run pytest -q",
                "    criterion_ref: 2",
                "    timeout_s: 60",
                "    shell: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    event_store_path = workspace / ".mobius" / "build" / "events.db"
    with EventStore(event_store_path) as store:
        for index, phase in enumerate(phases, start=1):
            store.append_event(
                "build-resume-fixture",
                "phase.completed",
                {
                    "phase": phase,
                    "phase_index": index,
                    "summary": f"completed {phase}",
                    "intent": "tiny TODO CLI",
                    "run_id": "build-resume-fixture",
                    "spec_yaml": str(workspace / "spec.yaml"),
                },
            )


def test_build_resume_enters_phase_after_latest_completed_event(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_completed_phases(workspace, "interview", "seed")

    result = run_mobius(
        "build",
        "--resume",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 0, result.stderr
    assert "[Phase 1/4 complete — Interview]" not in result.stdout
    assert "[Phase 2/4 complete — Seed]" not in result.stdout
    assert "[Phase 3/4 complete — Maturity]" in result.stdout
    assert "[Phase 4/4 complete — Scoring + Delivery]" in result.stdout


def test_build_resume_without_completed_phase_events_exits_usage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = run_mobius(
        "build",
        "--resume",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 2
    assert "requires at least one phase.completed event" in result.stderr
