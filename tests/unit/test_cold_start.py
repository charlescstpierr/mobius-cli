from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMPORT_BANNED_MODULES = {"subprocess", "sqlite3", "shlex", "rich.table", "rich.console"}


def _subprocess_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COV_CORE_") and not key.startswith("COVERAGE_")
    }
    env["UV_NO_SYNC"] = "1"
    return env


def test_cli_main_import_does_not_load_banned_modules() -> None:
    code = (
        "import importlib, sys; "
        "importlib.import_module('mobius.cli.main'); "
        f"banned = {IMPORT_BANNED_MODULES!r}; "
        "print(','.join(sorted(k for k in sys.modules if k in banned)))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
        env=_subprocess_env(),
    )

    assert result.stdout.strip() == ""


def test_uv_run_help_median_wall_clock_under_80ms() -> None:
    samples: list[float] = []
    env = _subprocess_env()
    for _ in range(5):
        start = time.perf_counter()
        subprocess.run(
            ["uv", "run", "mobius", "--help"],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            env=env,
        )
        samples.append(time.perf_counter() - start)

    assert statistics.median(samples) < 0.08, samples
