from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_v3a_real_llm_build_is_opt_in(tmp_path: Path) -> None:
    if os.environ.get("MOBIUS_RUN_REAL_LLM") != "1":
        pytest.skip("real LLM integration is opt-in and never runs on PR CI")

    env = {
        **os.environ,
        "MOBIUS_HOME": str(tmp_path / "home"),
        "MOBIUS_LLM_MODE": "real",
        "MOBIUS_V3A_WIZARD_COUNTDOWN": "0",
        "NO_COLOR": "1",
    }
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            "--directory",
            str(tmp_path),
            "mobius",
            "build",
            "tiny TODO CLI real LLM smoke",
            "--wizard",
            "--skip-tour",
            "--auto-top-up",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert list((tmp_path / ".mobius" / "build").glob("*/score.json"))
