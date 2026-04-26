import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_no_print_calls_outside_cli_output_module() -> None:
    first = subprocess.run(
        ["rg", "-n", r"^[^#]*\bprint\(", "src/mobius/"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode in {0, 1}

    matches = [
        line
        for line in first.stdout.splitlines()
        if not line.startswith("src/mobius/cli/output.py:")
    ]

    assert matches == []
