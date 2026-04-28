import json
import os
import subprocess
import time
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


def test_workflow_smoke_cli_runs_full_pipeline_under_10s(tmp_path: Path) -> None:
    started = time.monotonic()
    result = run_mobius("workflow", "smoke", "--json", mobius_home=tmp_path / "outer-home")
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert result.stderr == ""
    assert elapsed < 10
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["duration_ms"] < 10_000
    assert payload["run_id"].startswith("run_")
    assert [step["name"] for step in payload["steps"]] == [
        "init",
        "interview",
        "seed",
        "run",
        "status",
        "qa",
    ]
    assert all(step["passed"] for step in payload["steps"])
