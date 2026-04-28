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
goal: Exercise status reporting.
constraints:
  - Poll event-store deltas
  - Exit on terminal states
success_criteria:
  - JSON includes the required status fields
  - Follow mode streams progress until completion
""".strip(),
        encoding="utf-8",
    )


def test_status_without_run_id_opens_store_and_reapplies_missing_migration(
    tmp_path: Path,
) -> None:
    mobius_home = tmp_path / "mobius-home"
    initial = run_mobius("config", "show", "--json", mobius_home=mobius_home)
    assert initial.returncode == 0

    db_path = mobius_home / "events.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("DELETE FROM schema_migrations WHERE version = 1")
        connection.commit()
    finally:
        connection.close()

    result = run_mobius("status", "--json", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["migrations_applied"] is True
    assert payload["integrity_check"] == "ok"
    assert payload["event_count"] >= 1
    assert result.stderr == ""

    connection = sqlite3.connect(db_path)
    try:
        migration_count = connection.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()
        valid_payloads = connection.execute("SELECT json_valid(payload) FROM events").fetchall()
    finally:
        connection.close()

    assert migration_count[0] == 1
    assert {row[0] for row in valid_payloads} == {1}


def test_status_run_json_and_markdown_summary(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    started = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert started.returncode == 0

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        run_id = connection.execute(
            "SELECT session_id FROM sessions WHERE runtime = 'run'"
        ).fetchone()[0]
    finally:
        connection.close()

    json_result = run_mobius("status", run_id, "--json", mobius_home=mobius_home)
    assert json_result.returncode == 0
    payload = json.loads(json_result.stdout)
    assert set(payload) == {"run_id", "state", "started_at", "last_event_at"}
    assert payload["run_id"] == run_id
    assert payload["state"] == "completed"
    assert payload["started_at"].endswith("Z")
    assert payload["last_event_at"].endswith("Z")
    assert json_result.stderr == ""

    markdown_result = run_mobius("status", run_id, mobius_home=mobius_home)
    assert markdown_result.returncode == 0
    assert f"# Run {run_id}" in markdown_result.stdout
    assert "| State | completed |" in markdown_result.stdout
    assert markdown_result.stderr == ""


def test_status_unknown_run_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("status", "run_does_not_exist", mobius_home=tmp_path / "mobius-home")

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()


def test_status_run_slug_prefix_resolution_and_errors(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    first = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert first.returncode == 0
    second = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert second.returncode == 0

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        run_ids = [
            row[0]
            for row in connection.execute(
                "SELECT session_id FROM sessions WHERE runtime = 'run' ORDER BY started_at"
            ).fetchall()
        ]
    finally:
        connection.close()

    assert len(run_ids) == 2
    unique_prefix = run_ids[0].rsplit("_", 1)[0] + "_" + run_ids[0].rsplit("_", 1)[1][:4]
    common_prefix = run_ids[0].rsplit("_", 1)[0] + "_"

    resolved = run_mobius("status", unique_prefix, mobius_home=mobius_home)
    assert resolved.returncode == 0
    assert f"# Run {run_ids[0]}" in resolved.stdout

    missing = run_mobius("status", "xyz", mobius_home=mobius_home)
    assert missing.returncode != 0
    assert "not found" in missing.stderr.lower()

    ambiguous = run_mobius("status", common_prefix, mobius_home=mobius_home)
    assert ambiguous.returncode != 0
    assert "ambiguous run prefix" in ambiguous.stderr
    assert run_ids[0] in ambiguous.stderr
    assert run_ids[1] in ambiguous.stderr


def test_status_follow_streams_deltas_until_terminal_state(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    started = run_mobius("run", "--spec", str(spec), mobius_home=mobius_home)
    assert started.returncode == 0
    run_id = started.stdout.strip()

    follow = subprocess.Popen(
        ["uv", "run", "mobius", "status", run_id, "--follow"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )
    stdout, stderr = follow.communicate(timeout=10)

    assert follow.returncode == 0
    assert f"# Run {run_id}" in stdout
    assert "run.progress" in stdout
    assert "run.completed" in stdout
    assert "| State | completed |" in stdout
    assert stderr == ""

    pid_file = mobius_home / "runs" / run_id / "pid"
    deadline = time.monotonic() + 2
    while pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_file.exists()


def test_status_read_only_opens_mode_ro_without_wal_growth(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"
    initial = run_mobius("status", "--json", mobius_home=mobius_home)
    assert initial.returncode == 0

    db_path = mobius_home / "events.db"
    wal_path = Path(f"{db_path}-wal")
    before_size = wal_path.stat().st_size if wal_path.exists() else 0

    result = run_mobius("status", "--read-only", "--json", mobius_home=mobius_home)

    after_size = wal_path.stat().st_size if wal_path.exists() else 0
    assert result.returncode == 0
    assert json.loads(result.stdout)["read_only"] is True
    assert after_size == before_size
    assert result.stderr == ""
