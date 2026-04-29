from __future__ import annotations

import json
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


def write_low_maturity_spec(workspace: Path) -> None:
    (workspace / "spec.yaml").write_text(
        "\n".join(
            [
                "spec_version: 2",
                "project_type: greenfield",
                "goal: Ship a small CLI.",
                "constraints:",
                "  - deterministic behavior",
                "success_criteria:",
                "  - User can run the CLI.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def seed_resume_at_maturity(workspace: Path) -> None:
    with EventStore(workspace / ".mobius" / "build" / "events.db") as store:
        store.append_event(
            "build-maturity-fixture",
            "phase.completed",
            {
                "phase": "seed",
                "phase_index": 2,
                "summary": "seed fixture",
                "intent": "tiny CLI",
                "run_id": "build-maturity-fixture",
                "spec_yaml": str(workspace / "spec.yaml"),
            },
        )


def test_low_maturity_spec_blocks_then_auto_top_up_unblocks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_low_maturity_spec(workspace)
    seed_resume_at_maturity(workspace)

    blocked = run_mobius("build", "--resume", cwd=workspace, mobius_home=tmp_path / "home")

    assert blocked.returncode == 1
    assert "maturity score" in blocked.stderr
    assert "below required" in blocked.stderr

    topped_up = run_mobius(
        "build",
        "--resume",
        "--auto-top-up",
        "--agent",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert topped_up.returncode == 0, topped_up.stderr
    payloads = [json.loads(line) for line in topped_up.stdout.splitlines()]
    maturity_payload = next(payload for payload in payloads if payload["phase_done"] == "maturity")
    assert maturity_payload["maturity_score"] >= 0.8
    assert maturity_payload["maturity_top_up_questions"] > 0


def test_force_immature_logs_override_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_low_maturity_spec(workspace)
    seed_resume_at_maturity(workspace)

    result = run_mobius(
        "build",
        "--resume",
        "--force-immature",
        "--override-reason",
        "accepted by operator for test",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 0, result.stderr
    with EventStore(workspace / ".mobius" / "build" / "events.db", read_only=True) as store:
        event_types = [
            str(row["type"])
            for row in store.connection.execute(
                "SELECT type FROM events WHERE type IN "
                "('human.overrode', 'spec.maturity_overridden') ORDER BY sequence"
            ).fetchall()
        ]

    assert event_types == ["human.overrode", "spec.maturity_overridden"]
