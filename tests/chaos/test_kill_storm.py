import json
import os
import random
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TERMINAL_STATES = {"completed", "failed", "crashed", "cancelled", "interrupted"}


def run_mobius(*args: str, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def write_long_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Keep detached workers alive long enough for chaos testing.
constraints:
  - Step 1
  - Step 2
  - Step 3
  - Step 4
  - Step 5
  - Step 6
  - Step 7
  - Step 8
  - Step 9
  - Step 10
success_criteria:
  - Criterion 1
  - Criterion 2
  - Criterion 3
  - Criterion 4
  - Criterion 5
  - Criterion 6
  - Criterion 7
  - Criterion 8
  - Criterion 9
  - Criterion 10
""".strip(),
        encoding="utf-8",
    )


def wait_for_pid(pid_file: Path) -> int:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8").strip())
        time.sleep(0.05)
    raise AssertionError(f"PID file was not created: {pid_file}")


def wait_until_not_live(pid: int) -> None:
    deadline = time.monotonic() + 10
    while _pid_is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_process(pid: int) -> None:
    if not _pid_is_live(pid):
        return
    os.kill(pid, signal.SIGKILL)
    wait_until_not_live(pid)


def _session_state(mobius_home: Path, session_id: str) -> str:
    status = run_mobius("status", session_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0, status.stderr
    return str(json.loads(status.stdout)["state"])


def _assert_store_integrity(mobius_home: Path) -> None:
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        half_written_events = connection.execute(
            "SELECT count(*) FROM events WHERE payload IS NULL OR payload = ''"
        ).fetchone()
        half_written_sessions = connection.execute(
            "SELECT count(*) FROM sessions WHERE metadata IS NULL OR metadata = ''"
        ).fetchone()
    finally:
        connection.close()

    assert integrity[0] == "ok"
    assert half_written_events[0] == 0
    assert half_written_sessions[0] == 0


def _create_completed_run(tmp_path: Path, mobius_home: Path) -> str:
    spec = tmp_path / "evolution-source.yaml"
    write_long_spec(spec)
    result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert result.returncode == 0, result.stderr
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        row = connection.execute(
            "SELECT session_id FROM sessions WHERE runtime = 'run' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def test_parallel_run_kill_storm_recovers_without_orphans_or_half_written_rows(
    tmp_path: Path,
) -> None:
    # Feature 1.1b investigation: the observed 0 == 10 failure was reproducible
    # when local uv entry-point scripts pointed at a stale virtualenv. After
    # refreshing the dev environment, this chaos check passes and should stay
    # active rather than being skipped as flaky.
    mobius_home = tmp_path / "home"
    spec = tmp_path / "storm.yaml"
    write_long_spec(spec)

    launchers = [
        subprocess.Popen(
            ["uv", "run", "mobius", "run", "--spec", str(spec)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
        )
        for _ in range(10)
    ]
    launched = [launcher.communicate(timeout=15) for launcher in launchers]
    for launcher in launchers:
        assert launcher.returncode == 0
    run_ids = [stdout.strip() for stdout, stderr in launched if stderr == ""]
    assert len(run_ids) == 10

    rng = random.Random(5771)
    run_ids_in_kill_order = run_ids[:]
    rng.shuffle(run_ids_in_kill_order)
    pid_files = {run_id: mobius_home / "runs" / run_id / "pid" for run_id in run_ids}
    pids = {run_id: wait_for_pid(pid_files[run_id]) for run_id in run_ids}

    for run_id in run_ids_in_kill_order:
        time.sleep(rng.uniform(0.0, 0.03))
        _kill_process(pids[run_id])

    states = {_session_state(mobius_home, run_id) for run_id in run_ids}

    assert states <= TERMINAL_STATES
    assert not list((mobius_home / "runs").glob("run_*/pid"))
    _assert_store_integrity(mobius_home)


def test_evolution_pid_files_are_cleaned_after_sigkill_by_status_and_cancel(
    tmp_path: Path,
) -> None:
    mobius_home = tmp_path / "home"
    source_run_id = _create_completed_run(tmp_path, mobius_home)
    evolution_ids: list[str] = []
    pid_files: list[Path] = []
    pids: list[int] = []

    for _ in range(3):
        result = run_mobius(
            "evolve",
            "--from",
            source_run_id,
            "--generations",
            "30",
            mobius_home=mobius_home,
        )
        assert result.returncode == 0, result.stderr
        evolution_id = result.stdout.strip()
        pid_file = mobius_home / "evolutions" / evolution_id / "pid"
        evolution_ids.append(evolution_id)
        pid_files.append(pid_file)
        pid = wait_for_pid(pid_file)
        pids.append(pid)
        _kill_process(pid)

    status_cleaned_state = _session_state(mobius_home, evolution_ids[0])
    cancel_cleaned = run_mobius(
        "cancel",
        evolution_ids[1],
        "--grace-period",
        "0.1",
        mobius_home=mobius_home,
    )
    third_state = _session_state(mobius_home, evolution_ids[2])

    assert cancel_cleaned.returncode == 0, cancel_cleaned.stderr
    assert status_cleaned_state == "crashed"
    assert third_state == "crashed"
    assert _session_state(mobius_home, evolution_ids[1]) == "cancelled"
    assert not any(pid_file.exists() for pid_file in pid_files)
    _assert_store_integrity(mobius_home)
