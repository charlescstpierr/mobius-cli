from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_v3a_modules_do_not_import_banned_modules_at_top_level() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/lint_imports.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
