import json
import os
import signal
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = PROJECT_ROOT / ".venv" / "bin"


def run_installed_mobius(
    *args: str,
    mobius_home: Path,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MOBIUS_HOME": str(mobius_home),
        "NO_COLOR": "1",
        "PATH": f"{VENV_BIN}{os.pathsep}{os.environ['PATH']}",
    }
    return subprocess.run(
        ["mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def write_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Verify the installed Mobius console script.
constraints:
  - Invoke subprocess.run with mobius as argv0
  - Isolate state under a temporary home
success_criteria:
  - stdout stderr and exit code are asserted
  - PID files are cleaned up
""".strip(),
        encoding="utf-8",
    )


def wait_for_pid_file(mobius_home: Path, run_id: str) -> Path:
    pid_file = mobius_home / "runs" / run_id / "pid"
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists()
    return pid_file


def wait_for_no_pid_files(mobius_home: Path) -> None:
    deadline = time.monotonic() + 10
    while list(mobius_home.glob("runs/*/pid")) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(mobius_home.glob("runs/*/pid")) == []


def test_installed_binary_subprocess_e2e_asserts_stdio_exit_codes_and_cleanup(
    tmp_path: Path,
) -> None:
    mobius_home = tmp_path / "mobius-home"
    spec = tmp_path / "spec.yaml"
    write_spec(spec)

    help_result = run_installed_mobius("--help", mobius_home=mobius_home)
    run_result = run_installed_mobius("run", "--spec", str(spec), mobius_home=mobius_home)

    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout
    assert help_result.stderr == ""
    assert run_result.returncode == 0
    assert run_result.stdout.startswith("run_")
    assert run_result.stderr == ""

    run_id = run_result.stdout.strip()
    wait_for_pid_file(mobius_home, run_id)
    wait_for_no_pid_files(mobius_home)
    status_result = run_installed_mobius(
        "status",
        run_id,
        "--json",
        mobius_home=mobius_home,
    )
    status_payload = json.loads(status_result.stdout)

    assert status_result.returncode == 0
    assert status_result.stderr == ""
    assert status_payload["run_id"] == run_id
    assert status_payload["state"] == "completed"
    assert list(mobius_home.glob("runs/*/pid")) == []


def test_installed_binary_documents_and_exercises_standard_exit_codes(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"
    invalid_spec = tmp_path / "invalid.yaml"
    invalid_spec.write_text(
        "project_type: greenfield\ngoal:\nconstraints:\nsuccess_criteria:\n",
        encoding="utf-8",
    )
    long_spec = tmp_path / "long.yaml"
    write_spec(long_spec)

    ok = run_installed_mobius("--version", mobius_home=mobius_home)
    usage = run_installed_mobius("bogus-subcmd", mobius_home=mobius_home)
    validation = run_installed_mobius("run", "--spec", str(invalid_spec), mobius_home=mobius_home)
    not_found = run_installed_mobius("status", "run_missing", mobius_home=mobius_home)

    env = {
        **os.environ,
        "MOBIUS_HOME": str(mobius_home),
        "NO_COLOR": "1",
        "PATH": f"{VENV_BIN}{os.pathsep}{os.environ['PATH']}",
    }
    interrupted = subprocess.Popen(
        ["mobius", "run", "--foreground", "--spec", str(long_spec)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    pid_file: Path | None = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        pid_files = list(mobius_home.glob("runs/*/pid"))
        if pid_files:
            pid_file = pid_files[0]
            break
        time.sleep(0.05)
    assert pid_file is not None
    os.kill(int(pid_file.read_text(encoding="utf-8").strip()), signal.SIGINT)
    stdout, stderr = interrupted.communicate(timeout=10)

    assert ok.returncode == 0
    assert ok.stdout.startswith("mobius ")
    assert ok.stderr == ""
    assert usage.returncode == 2
    assert usage.stdout == ""
    assert "No such command" in usage.stderr
    assert validation.returncode == 3
    assert validation.stdout == ""
    assert "seed spec validation failed" in validation.stderr
    assert not_found.returncode == 4
    assert not_found.stdout == ""
    assert "not found" in not_found.stderr
    assert interrupted.returncode == 130
    assert stdout == ""
    assert "interrupted" in stderr
    wait_for_no_pid_files(mobius_home)
    assert not pid_file.exists()
