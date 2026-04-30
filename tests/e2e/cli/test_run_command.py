import json
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def write_valid_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Execute a deterministic Mobius run.
constraints:
  - Fork workers by default
  - Persist transactional events
success_criteria:
  - Run id is returned immediately
  - PID file is cleaned up after completion
""".strip(),
        encoding="utf-8",
    )


def write_long_running_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Keep the foreground run alive long enough for signal tests.
constraints:
  - Step 1
  - Step 2
  - Step 3
  - Step 4
  - Step 5
success_criteria:
  - Criterion 1
  - Criterion 2
  - Criterion 3
  - Criterion 4
  - Criterion 5
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


def wait_for_any_pid_file(mobius_home: Path) -> Path:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        matches = list((mobius_home / "runs").glob("run_*/pid"))
        if matches:
            return matches[0]
        time.sleep(0.05)
    raise AssertionError("foreground run did not write a PID file")


def wait_for_no_pid_file(pid_file: Path) -> None:
    deadline = time.monotonic() + 10
    while pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_file.exists()


def pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def start_foreground_run(spec: Path, mobius_home: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["uv", "run", "mobius", "run", "--foreground", "--spec", str(spec)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def test_run_defaults_to_detach_writes_pid_and_cleans_up(tmp_path: Path, mobius_runner) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    started = time.monotonic()
    result = mobius_runner("run", "--spec", str(spec), mobius_home=mobius_home)
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    # F10 stabilization: process start latency can exceed 1s on loaded CI/dev
    # hosts even when detach returns promptly; keep a bounded 2s UX budget.
    assert elapsed < 2
    run_id = result.stdout.strip()
    assert run_id.startswith("run_")
    assert result.stderr == ""

    pid_file = wait_for_pid_file(mobius_home, run_id)
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert pid_is_live(pid)
    assert (mobius_home / "runs" / run_id / "log").exists()

    wait_for_no_pid_file(pid_file)
    status = mobius_runner("status", run_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    payload = json.loads(status.stdout)
    assert payload["run_id"] == run_id
    assert payload["state"] == "completed"


def test_run_foreground_blocks_streams_events_and_cleans_pid(tmp_path: Path, mobius_runner) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    result = mobius_runner("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)

    assert result.returncode == 0
    assert result.stdout == ""
    assert "run.started" in result.stderr
    assert "run.completed" in result.stderr
    assert not list((mobius_home / "runs").glob("*/pid"))


def test_run_foreground_sigterm_cancels_and_cleans_pid(tmp_path: Path, mobius_runner) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "long.yaml"
    write_long_running_spec(spec)
    process = start_foreground_run(spec, mobius_home)
    pid_file = wait_for_any_pid_file(mobius_home)
    run_id = pid_file.parent.name
    worker_pid = int(pid_file.read_text(encoding="utf-8").strip())

    os.kill(worker_pid, signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0
    assert stdout == ""
    assert "run.started" in stderr
    assert not pid_file.exists()
    status = mobius_runner("status", run_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    assert json.loads(status.stdout)["state"] == "cancelled"


def test_run_foreground_sigint_exits_130_with_interrupted_and_cleans_pid(
    tmp_path: Path, mobius_runner
) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "long.yaml"
    write_long_running_spec(spec)
    process = start_foreground_run(spec, mobius_home)
    pid_file = wait_for_any_pid_file(mobius_home)
    run_id = pid_file.parent.name
    worker_pid = int(pid_file.read_text(encoding="utf-8").strip())

    os.kill(worker_pid, signal.SIGINT)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 130
    assert stdout == ""
    assert "interrupted" in stderr
    assert not pid_file.exists()
    status = mobius_runner("status", run_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    assert json.loads(status.stdout)["state"] == "interrupted"


def test_run_rejects_invalid_spec_with_exit_3(tmp_path: Path, mobius_runner) -> None:
    spec = tmp_path / "invalid.yaml"
    spec.write_text("project_type: greenfield\ngoal:\nconstraints:\nsuccess_criteria:\n")

    result = mobius_runner("run", "--spec", str(spec), mobius_home=tmp_path / "home")

    assert result.returncode == 3
    assert "seed spec validation failed" in result.stderr
    assert result.stdout == ""


def test_concurrent_detached_runs_keep_event_store_integrity(tmp_path: Path, mobius_runner) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    processes = [
        subprocess.Popen(
            ["uv", "run", "mobius", "run", "--spec", str(spec)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
        )
        for _ in range(5)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    run_ids = [stdout.strip() for stdout, stderr in results if stderr == ""]

    assert len(run_ids) == 5
    for process in processes:
        assert process.returncode == 0
    for run_id in run_ids:
        wait_for_no_pid_file(mobius_home / "runs" / run_id / "pid")

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        for run_id in run_ids:
            sequences = [
                row[0]
                for row in connection.execute(
                    "SELECT sequence FROM events WHERE aggregate_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
            ]
            assert sequences == list(range(1, len(sequences) + 1))
    finally:
        connection.close()

    assert integrity[0] == "ok"


def test_sigkill_worker_cleanup_on_subsequent_status(tmp_path: Path, mobius_runner) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    result = mobius_runner("run", "--spec", str(spec), mobius_home=mobius_home)
    assert result.returncode == 0
    run_id = result.stdout.strip()
    pid_file = wait_for_pid_file(mobius_home, run_id)
    pid = int(pid_file.read_text(encoding="utf-8").strip())

    os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while pid_is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    status = mobius_runner("status", run_id, "--json", mobius_home=mobius_home)

    assert status.returncode == 0
    assert json.loads(status.stdout)["state"] == "crashed"
    assert not pid_file.exists()
