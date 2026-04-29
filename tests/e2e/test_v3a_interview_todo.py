from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


def run_mobius(
    *args: str,
    mobius_home: Path,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(MOBIUS_BIN), *args],
        cwd=cwd or PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MOBIUS_HOME": str(mobius_home),
            "NO_COLOR": "1",
            "PATH": f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )


def test_todo_cli_fixture_converges_without_deadlock(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = run_mobius(
        "build",
        "tiny TODO CLI",
        "--agent",
        mobius_home=tmp_path / "home",
        cwd=workspace,
    )

    assert result.returncode == 0, result.stderr
    payload = _payload_for_phase(result.stdout, "seed")
    interview_payload = _payload_for_phase(result.stdout, "interview")
    assert payload["phase_done"] == "seed"
    assert payload["next_phase"] == "maturity"
    assert payload["turns"] <= 8
    assert payload["ambiguity_score"] < 0.2
    assert payload["max_component"] < 0.4
    assert interview_payload["converged_proposed"] is True
    assert payload["human_confirmed"] is True

    transcript = Path(payload["transcript"])
    fixture = Path(payload["fixture"])
    assert transcript.exists()
    assert fixture.exists()
    assert Path(payload["spec_yaml"]).exists()
    text = transcript.read_text(encoding="utf-8")
    assert "Hypothetical:" in text
    assert "**Architecte:**" in text
    assert "because:" in text
    assert "TODO" in fixture.read_text(encoding="utf-8")


def test_build_help_documents_modes(tmp_path: Path) -> None:
    result = run_mobius("build", "--help", mobius_home=tmp_path / "home")

    assert result.returncode == 0
    assert "--interactive" in result.stdout
    assert "--wizard" in result.stdout
    assert "--agent" in result.stdout


def _payload_for_phase(stdout: str, phase: str) -> dict[str, object]:
    for line in stdout.splitlines():
        payload = json.loads(line)
        if payload.get("phase_done") == phase:
            return payload
    raise AssertionError(f"missing phase payload for {phase!r}: {stdout}")
