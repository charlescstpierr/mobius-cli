import json
import sqlite3
from pathlib import Path

import pytest

from mobius.persistence.event_store import EventStore, iso8601_utc_now


def test_event_store_session_lifecycle_and_replay_payloads(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "events.db"

    with EventStore(db_path) as store:
        store.create_session("run_release", runtime="run", metadata={"source": "test"})
        first = store.append_event("run_release", "run.started", {"step": 1})
        second = store.append_event("run_release", "run.completed", {"ok": True})
        store.end_session("run_release", status="completed")
        session = store.connection.execute(
            "SELECT runtime, metadata, status, ended_at FROM sessions WHERE session_id = ?",
            ("run_release",),
        ).fetchone()
        events = store.read_events("run_release")

    assert first.sequence == 1
    assert second.sequence == 2
    assert [event.payload_data for event in events] == [{"step": 1}, {"ok": True}]
    assert session["runtime"] == "run"
    assert json.loads(session["metadata"]) == {"source": "test"}
    assert session["status"] == "completed"
    assert session["ended_at"].endswith("Z")


def test_read_only_store_requires_existing_migrations_and_refuses_session_writes(
    tmp_path: Path,
) -> None:
    missing_db_path = tmp_path / "missing" / "events.db"
    with pytest.raises(sqlite3.OperationalError):
        EventStore(missing_db_path, read_only=True)

    db_path = tmp_path / "events.db"
    with EventStore(db_path):
        pass

    with EventStore(db_path, read_only=True) as readonly:
        assert readonly.integrity_check() == "ok"
        with pytest.raises(PermissionError):
            readonly.create_session("run_readonly", runtime="run")


def test_iso8601_utc_now_uses_z_suffix_and_microseconds() -> None:
    timestamp = iso8601_utc_now()

    assert timestamp.endswith("Z")
    date, time = timestamp[:-1].split("T")
    assert len(date.split("-")) == 3
    assert "." in time
    assert len(time.rsplit(".", maxsplit=1)[1]) == 6
