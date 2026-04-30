from __future__ import annotations

import json
from pathlib import Path


def test_full_build_score_is_stable_across_five_reruns(tmp_path: Path, mobius_runner) -> None:
    scores: list[int] = []
    for index in range(5):
        workspace = tmp_path / f"workspace-{index}"
        workspace.mkdir()
        result = mobius_runner(
            "build",
            "tiny TODO CLI",
            "--agent",
            "--auto-top-up",
            cwd=workspace,
            mobius_home=tmp_path / f"home-{index}",
            extra_env={"MOBIUS_LLM_MODE": "mock", "MOBIUS_V3A_WIZARD_COUNTDOWN": "0"},
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
