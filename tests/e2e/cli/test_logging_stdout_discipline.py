import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_log_records_go_to_stderr_and_never_stdout() -> None:
    script = (
        "from mobius.logging import configure_logging, get_logger;"
        "configure_logging(level='INFO', force=True);"
        "get_logger('mobius.e2e.logging').info('MOBIUS_LOG_MARKER_E2E')"
    )

    result = subprocess.run(
        ["uv", "run", sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "NO_COLOR": "1"},
    )

    assert result.returncode == 0
    assert "MOBIUS_LOG_MARKER_E2E" not in result.stdout
    assert "MOBIUS_LOG_MARKER_E2E" in result.stderr
    assert "INFO" in result.stderr


def test_cli_json_flag_keeps_stdout_free_of_log_markers() -> None:
    result = subprocess.run(
        ["uv", "run", "mobius", "--json", "status"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "INFO" not in result.stdout
    assert "DEBUG" not in result.stdout
    assert "WARNING" not in result.stdout
    assert "ERROR" not in result.stdout
