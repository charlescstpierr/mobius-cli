import json
import os
import signal
import sqlite3
import subprocess
import sys
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


def write_valid_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Exercise cancellation.
constraints:
  - Cancel running workers
success_criteria:
  - PID file is removed
  - Session is marked cancelled
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


def pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_cancel_running_run_exits_zero_removes_pid_and_marks_cancelled(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    started = run_mobius("run", "--spec", str(spec), mobius_home=mobius_home)
    assert started.returncode == 0
    run_id = started.stdout.strip()
    pid_file = wait_for_pid_file(mobius_home, run_id)
    pid = int(pid_file.read_text(encoding="utf-8").strip())

    result = run_mobius("cancel", run_id, "--grace-period", "0.2", mobius_home=mobius_home)

    assert result.returncode == 0
    assert result.stderr == ""
    assert f"cancelled {run_id}" in result.stdout
    assert not pid_file.exists()

    deadline = time.monotonic() + 5
    while pid_is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_is_live(pid)

    status = run_mobius("status", run_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    assert json.loads(status.stdout)["state"] == "cancelled"


def test_cancel_unknown_run_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius(
        "cancel",
        "run_does_not_exist",
        "--grace-period",
        "0.01",
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()


def test_cancel_completed_run_exits_zero_without_pid(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    completed = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert completed.returncode == 0

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        run_id = connection.execute(
            "SELECT session_id FROM sessions WHERE runtime = 'run'"
        ).fetchone()[0]
    finally:
        connection.close()

    result = run_mobius("cancel", run_id, "--grace-period", "0.01", mobius_home=mobius_home)

    assert result.returncode == 0
    assert result.stderr == ""
    assert f"already finished {run_id}" in result.stdout


def test_cancel_escalates_sigterm_ignoring_process(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id = "run_ignores_term"
    setup = run_mobius("status", "--json", mobius_home=mobius_home)
    assert setup.returncode == 0
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        connection.execute(
            "INSERT INTO sessions(session_id, started_at, ended_at, runtime, metadata, status) "
            "VALUES (?, '2026-01-01T00:00:00Z', NULL, 'run', '{}', 'running')",
            (run_id,),
        )
        connection.commit()
    finally:
        connection.close()

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import signal,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "print('ready', flush=True);"
                "time.sleep(60)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    pid_file = mobius_home / "runs" / run_id / "pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

    try:
        result = run_mobius(
            "cancel",
            run_id,
            "--grace-period",
            "0.05",
            mobius_home=mobius_home,
        )
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert result.returncode == 0
    assert process.returncode == -signal.SIGKILL
    assert not pid_file.exists()
