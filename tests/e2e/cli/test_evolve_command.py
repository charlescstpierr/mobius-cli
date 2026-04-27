import json
import os
import sqlite3
import subprocess
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
goal: Exercise evolution progress.
constraints:
  - Generate candidates
  - Detect convergence
success_criteria:
  - Evolution detaches by default
  - Status follow streams generation progress
""".strip(),
        encoding="utf-8",
    )


def create_completed_run(tmp_path: Path, mobius_home: Path) -> str:
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert result.returncode == 0
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        return str(
            connection.execute("SELECT session_id FROM sessions WHERE runtime = 'run'").fetchone()[
                0
            ]
        )
    finally:
        connection.close()


def wait_for_pid_file(mobius_home: Path, evolution_id: str) -> Path:
    pid_file = mobius_home / "evolutions" / evolution_id / "pid"
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists()
    return pid_file


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


def test_evolve_help_lists_required_flags(tmp_path: Path) -> None:
    result = run_mobius("evolve", "--help", mobius_home=tmp_path / "home")

    assert result.returncode == 0
    assert "--from" in result.stdout
    assert "--generations" in result.stdout
    assert "--detach" in result.stdout


def test_evolve_defaults_to_detach_writes_pid_and_completes(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id = create_completed_run(tmp_path, mobius_home)

    started = time.monotonic()
    result = run_mobius("evolve", "--from", run_id, "--generations", "2", mobius_home=mobius_home)
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 1
    evolution_id = result.stdout.strip()
    assert evolution_id.startswith("evo_")
    assert result.stderr == ""

    pid_file = wait_for_pid_file(mobius_home, evolution_id)
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert pid_is_live(pid)
    assert (mobius_home / "evolutions" / evolution_id / "log").exists()

    wait_for_no_pid_file(pid_file)
    status = run_mobius("status", evolution_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    payload = json.loads(status.stdout)
    assert payload["run_id"] == evolution_id
    assert payload["state"] == "completed"


def test_evolve_status_follow_streams_generation_progress(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id = create_completed_run(tmp_path, mobius_home)
    started = run_mobius(
        "evolve",
        "--from",
        run_id,
        "--generations",
        "2",
        mobius_home=mobius_home,
    )
    assert started.returncode == 0
    evolution_id = started.stdout.strip()

    follow = subprocess.Popen(
        ["uv", "run", "mobius", "status", evolution_id, "--follow"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )
    stdout, stderr = follow.communicate(timeout=10)

    assert follow.returncode == 0
    assert "evolution.generation" in stdout
    assert "evolution.completed" in stdout
    assert f"# Run {evolution_id}" in stdout
    assert stderr == ""


def test_cancel_running_evolution_removes_pid_and_marks_cancelled(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id = create_completed_run(tmp_path, mobius_home)
    started = run_mobius(
        "evolve",
        "--from",
        run_id,
        "--generations",
        "30",
        mobius_home=mobius_home,
    )
    assert started.returncode == 0
    evolution_id = started.stdout.strip()
    pid_file = wait_for_pid_file(mobius_home, evolution_id)

    result = run_mobius(
        "cancel",
        evolution_id,
        "--grace-period",
        "0.2",
        mobius_home=mobius_home,
    )

    assert result.returncode == 0
    assert f"cancelled {evolution_id}" in result.stdout
    assert not pid_file.exists()
    status = run_mobius("status", evolution_id, "--json", mobius_home=mobius_home)
    assert status.returncode == 0
    assert json.loads(status.stdout)["state"] == "cancelled"


def test_evolve_unknown_source_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("evolve", "--from", "run_missing", mobius_home=tmp_path / "home")

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()
