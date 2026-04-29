from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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


def test_full_build_walkthrough_announces_all_four_phases(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = run_mobius(
        "build",
        "tiny TODO CLI",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 0, result.stderr
    assert "[Phase 1/4 complete — Interview]" in result.stdout
    assert "[Phase 2/4 complete — Seed]" in result.stdout
    assert "[Phase 3/4 complete — Maturity]" in result.stdout
    assert "[Phase 4/4 complete — Scoring + Delivery]" in result.stdout
    assert (workspace / "spec.yaml").exists()


def test_agent_mode_returns_json_for_each_completed_phase(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = run_mobius(
        "build",
        "tiny TODO CLI",
        "--agent",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 0, result.stderr
    payloads = [json.loads(line) for line in result.stdout.splitlines()]
    assert [payload["phase_done"] for payload in payloads] == [
        "interview",
        "seed",
        "maturity",
        "scoring",
    ]
    for payload in payloads:
        assert {"phase_done", "next_phase", "next_command"}.issubset(payload)
