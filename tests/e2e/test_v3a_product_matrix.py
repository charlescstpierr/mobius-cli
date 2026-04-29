from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from mobius.workflow.seed import load_seed_spec

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PRODUCT_INTENTS = [
    ("cli", "tiny TODO CLI with add list and done commands"),
    ("lib", "Python library that formats color palettes for designers"),
    ("web-api", "web API that stores bookmarks with tags and health checks"),
]


def run_mobius_build(intent: str, *, workspace: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MOBIUS_HOME": str(workspace / ".home"),
        "MOBIUS_LLM_MODE": "mock",
        "MOBIUS_V3A_WIZARD_COUNTDOWN": "0",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            "--directory",
            str(workspace),
            "mobius",
            "build",
            intent,
            "--wizard",
            "--skip-tour",
            "--auto-top-up",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_v3a_product_matrix_converges_with_mock_llm_and_writes_artifacts(
    tmp_path: Path,
) -> None:
    for product, intent in PRODUCT_INTENTS:
        workspace = tmp_path / product
        workspace.mkdir()

        result = run_mobius_build(intent, workspace=workspace)

        assert result.returncode == 0, result.stderr + result.stdout
        assert result.stderr == ""
        assert _turn_count(result.stdout) <= 12
        spec = load_seed_spec(workspace / "spec.yaml")
        assert spec.goal
        assert spec.success_criteria
        score_paths = list((workspace / ".mobius" / "build").glob("*/score.json"))
        assert len(score_paths) == 1
        payload = json.loads(score_paths[0].read_text(encoding="utf-8"))
        assert isinstance(payload["score_out_of_10"], int)
        assert 0 <= payload["score_out_of_10"] <= 10
        assert payload["score_breakdown"]["llm"]["model"] == "mobius-v3a-mock-judge"


def _turn_count(output: str) -> int:
    match = re.search(r"after (\d+) turns", output)
    assert match is not None, output
    return int(match.group(1))
