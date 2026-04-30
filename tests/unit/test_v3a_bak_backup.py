from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_scribe_module_has_no_top_level_subprocess_import() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/lint_imports.py",
            "--check",
            "src/mobius/v3a/interview/scribe.py",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
