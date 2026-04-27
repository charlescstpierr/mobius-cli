import json
import os
import sqlite3
import subprocess
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
