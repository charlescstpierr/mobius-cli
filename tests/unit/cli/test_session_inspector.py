"""Unit tests for the shared SessionInspector seam and its adapters."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from mobius.cli.session_inspector import (
    EventStoreSessionAdapter,
    RunStatus,
    SessionInspector,
    SQLiteSessionAdapter,
)
from mobius.persistence.event_store import EventStore, _canonical_json


def _connect(db_path: Path, read_only: bool) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
    else:
        connection = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _sqlite_inspector(home: Path, *, now: str = "2026-04-29T00:00:00.000000Z") -> SessionInspector:
    return SessionInspector(
        state_dir=home,
        adapter=SQLiteSessionAdapter(
            home / "events.db",
            connect=_connect,
            now=lambda: now,
            canonical_json=_canonical_json,
        ),
    )


def _event_store_inspector(home: Path) -> SessionInspector:
    return SessionInspector(
        state_dir=home,
        adapter=EventStoreSessionAdapter(home / "events.db"),
    )


def _session_row(home: Path, session_id: str) -> Any:
    with EventStore(home / "events.db") as store:
        return store.connection.execute(
            "SELECT runtime, status FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()


def test_sqlite_adapter_reads_and_resolves_run_status(tmp_path: Path) -> None:
    home = tmp_path / "home"
    with EventStore(home / "events.db") as store:
        store.create_session("run_alpha", runtime="run", metadata={}, status="completed")
        store.append_event("run_alpha", "run.started", {"goal": "Alpha"})

    inspector = _sqlite_inspector(home)
    status = inspector.read_run_status("run_alpha")

    assert inspector.resolve_run_id("latest") == "run_alpha"
    assert inspector.resolve_run_id("run_al") == "run_alpha"
    assert status is not None
    assert status == RunStatus(
        run_id="run_alpha",
        state="completed",
        started_at=status.started_at,
        last_event_at=status.last_event_at,
    )


def test_sqlite_adapter_marks_orphan_stale_pid_as_crashed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    with EventStore(home / "events.db"):
        pass
    pid_file = home / "runs" / "run_orphan" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("2999998\n", encoding="utf-8")

    _sqlite_inspector(home).mark_stale_session_if_needed("run_orphan")

    row = _session_row(home, "run_orphan")
    assert row["runtime"] == "run"
    assert row["status"] == "crashed"
    assert not pid_file.exists()


def test_event_store_adapter_marks_existing_stale_pid_as_crashed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    with EventStore(home / "events.db") as store:
        store.create_session("run_stale", runtime="run", metadata={}, status="running")
    pid_file = home / "runs" / "run_stale" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("2999997\n", encoding="utf-8")

    _event_store_inspector(home).mark_stale_session_if_needed("run_stale")

    row = _session_row(home, "run_stale")
    assert row["status"] == "crashed"
    assert not pid_file.exists()
