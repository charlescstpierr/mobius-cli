from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


@pytest.fixture
def mobius_runner() -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        *args: str,
        mobius_home: Path,
        cwd: Path | None = None,
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
        path_mode: str = "prepend",
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "MOBIUS_HOME": str(mobius_home),
            "NO_COLOR": "1",
        }
        if path_mode == "prepend":
            env["PATH"] = f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        elif path_mode == "bin_only":
            env["PATH"] = str(MOBIUS_BIN.parent)
        elif path_mode != "inherit":
            raise ValueError(f"unknown path_mode: {path_mode}")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [str(MOBIUS_BIN), *args],
            cwd=cwd or PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
            timeout=timeout,
        )

    return _run
