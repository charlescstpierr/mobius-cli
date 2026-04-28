import json
import re
import sqlite3
from pathlib import Path

import pytest

from mobius.persistence.event_store import EventStore


def test_open_sets_required_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "events.db"

    with EventStore(db_path) as store:
        journal_mode = store.connection.execute("PRAGMA journal_mode").fetchone()
        busy_timeout = store.connection.execute("PRAGMA busy_timeout").fetchone()
        synchronous = store.connection.execute("PRAGMA synchronous").fetchone()
        foreign_keys = store.connection.execute("PRAGMA foreign_keys").fetchone()

    assert journal_mode[0] == "wal"
    assert busy_timeout[0] == 30_000
    assert synchronous[0] == 1
    assert foreign_keys[0] == 1


def test_schema_tables_columns_and_indices_exist(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path):
        pass

    connection = sqlite3.connect(db_path)
    try:
        columns = {
            table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            for table in ("events", "sessions", "aggregates", "schema_migrations")
        }
        index_sql = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='events'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert columns["events"] == {
        "event_id",
        "aggregate_id",
        "sequence",
        "type",
        "payload",
        "created_at",
    }
    assert columns["sessions"] == {
        "session_id",
        "started_at",
        "ended_at",
        "runtime",
        "metadata",
        "status",
    }
    assert columns["aggregates"] == {
        "aggregate_id",
        "type",
        "last_sequence",
        "snapshot",
        "updated_at",
    }
    assert columns["schema_migrations"] == {"version", "applied_at"}
    explicit_index_sql = [sql.replace("\n", " ") for sql in index_sql.values() if sql is not None]
    assert any("UNIQUE" in sql and "aggregate_id, sequence" in sql for sql in explicit_index_sql)
    assert any("aggregate_id" in sql and "sequence" not in sql for sql in explicit_index_sql)


def test_db_and_parent_directory_permissions_are_restricted(tmp_path: Path) -> None:
    db_path = tmp_path / "mobius-home" / "events.db"

    with EventStore(db_path):
        pass

    assert db_path.stat().st_mode & 0o777 == 0o600
    assert db_path.parent.stat().st_mode & 0o777 == 0o700


def test_migrations_are_version_tracked_and_auto_reapplied(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        rows = store.connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        store.connection.execute("DELETE FROM schema_migrations WHERE version = 1")

    with EventStore(db_path) as store:
        reapplied = store.connection.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [row["version"] for row in rows] == [1]
    assert [row["version"] for row in reapplied] == [1]
    assert reapplied[0]["applied_at"].endswith("Z")


def test_open_writes_idempotent_bootstrap_event_with_valid_json(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        rows = store.connection.execute(
            """
            SELECT aggregate_id, sequence, type, json_valid(payload) AS valid_payload
            FROM events
            WHERE aggregate_id = 'mobius.bootstrap'
            """
        ).fetchall()

    with EventStore(db_path) as store:
        bootstrap_count = store.connection.execute(
            "SELECT count(*) FROM events WHERE aggregate_id = 'mobius.bootstrap'"
        ).fetchone()

    bootstrap_rows = [
        (row["aggregate_id"], row["sequence"], row["type"], row["valid_payload"]) for row in rows
    ]
    assert bootstrap_rows == [("mobius.bootstrap", 1, "mobius.bootstrap", 1)]
    assert bootstrap_count[0] == 1


def test_append_event_enforces_json_and_iso8601_utc_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        event = store.append_event("agg-1", "seed.created", {"answer": 42})
        json_valid = store.connection.execute(
            "SELECT json_valid(payload) FROM events ORDER BY aggregate_id"
        ).fetchall()
        created_at_values = store.connection.execute(
            "SELECT created_at FROM events ORDER BY aggregate_id, sequence"
        ).fetchall()

    assert event.sequence == 1
    assert json.loads(event.payload) == {"answer": 42}
    assert {row[0] for row in json_valid} == {1}
    assert [row[0].endswith("Z") for row in created_at_values] == [True, True]
    for row in created_at_values:
        assert re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
            row[0],
        )


def test_unique_aggregate_sequence_makes_append_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        first = store.append_event(
            "agg-1",
            "seed.created",
            {"value": "first"},
            sequence=1,
            event_id="event-1",
        )
        duplicate = store.append_event(
            "agg-1",
            "seed.created",
            {"value": "duplicate"},
            sequence=1,
            event_id="event-duplicate",
        )
        rows = store.read_events("agg-1")

    assert first == duplicate
    assert len(rows) == 1
    assert rows[0].event_id == "event-1"
    assert rows[0].payload_data == {"value": "first"}


def test_replay_hash_is_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        store.append_event("agg-1", "first", {"b": 2, "a": 1})
        store.append_event("agg-1", "second", {"nested": {"z": True}})
        hash_one = store.replay_hash("agg-1")
        hash_two = store.replay_hash("agg-1")

    with EventStore(db_path) as reopened_store:
        hash_after_reopen = reopened_store.replay_hash("agg-1")

    assert hash_one == hash_two == hash_after_reopen
    assert re.fullmatch(r"[0-9a-f]{64}", hash_one)
    assert len(hash_one) == 64


def test_read_only_mode_uses_uri_and_refuses_writes_without_wal_growth(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        store.append_event("agg-1", "first", {"ok": True})
        store.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    wal_path = Path(f"{db_path}-wal")
    before_size = wal_path.stat().st_size if wal_path.exists() else 0

    with EventStore(db_path, read_only=True) as store:
        events = store.read_events("agg-1")
        with pytest.raises(PermissionError):
            store.append_event("agg-1", "second", {"ok": False})

    after_size = wal_path.stat().st_size if wal_path.exists() else 0
    assert [event.type for event in events] == ["first"]
    assert after_size == before_size


def test_integrity_check_returns_ok_after_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        store.append_event("agg-1", "first", {"ok": True})

    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"


def test_run_slug_prefix_lookup_and_latest_run(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        first = store.append_event("abc-def-123", "run.started", {"goal": "First"})
        store.append_event("abc-def-123", "run.completed", {"ok": True})
        second = store.append_event("abc-different-456", "run.started", {"goal": "Second"})

        exact_prefix = store.find_by_slug_prefix("abc-def")
        ambiguous_prefix = store.find_by_slug_prefix("abc-")
        latest = store.get_latest_run()

    assert exact_prefix == [first]
    assert [event.aggregate_id for event in ambiguous_prefix] == [
        "abc-different-456",
        "abc-def-123",
    ]
    assert latest == second
