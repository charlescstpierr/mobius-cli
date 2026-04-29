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
            "MOBIUS_LLM_MODE": "mock",
            "MOBIUS_V3A_WIZARD_COUNTDOWN": "0",
            "NO_COLOR": "1",
            "PATH": f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )


def test_full_build_score_is_stable_across_five_reruns(tmp_path: Path) -> None:
    scores: list[int] = []
    for index in range(5):
        workspace = tmp_path / f"workspace-{index}"
        workspace.mkdir()
        result = run_mobius(
            "build",
            "tiny TODO CLI",
            "--agent",
            "--auto-top-up",
            cwd=workspace,
            mobius_home=tmp_path / f"home-{index}",
        )

        assert result.returncode == 0, result.stderr
        payloads = [json.loads(line) for line in result.stdout.splitlines()]
        scoring_payload = payloads[-1]
        score_path = Path(scoring_payload["score_json"])
        score = json.loads(score_path.read_text(encoding="utf-8"))
        scores.append(score["score_out_of_10"])
        assert scoring_payload["score_out_of_10"] == score["score_out_of_10"]
        assert "prompt_hash" in score["score_breakdown"]["llm"]

    assert max(scores) - min(scores) <= 1
