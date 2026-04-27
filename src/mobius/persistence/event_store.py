"""SQLite event store with WAL, migrations, and deterministic replay."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

_SQLITE_TIMEOUT_SECONDS = 30.0
_BUSY_TIMEOUT_MS = 30_000
_DB_FILE_MODE = 0o600
_DB_DIR_MODE = 0o700


def iso8601_utc_now() -> str:
    """Return the canonical Mobius UTC timestamp representation."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class EventRecord:
    """A persisted event-store row."""

    event_id: str
    aggregate_id: str
    sequence: int
    type: str
    payload: str
    created_at: str

    @property
    def payload_data(self) -> Any:
        """Deserialize the JSON payload."""
        return json.loads(self.payload)


@dataclass(frozen=True)
class Migration:
    """A versioned SQLite migration."""

    version: int
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        sql="""
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    aggregate_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL CHECK (json_valid(payload)),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_aggregate_sequence
    ON events (aggregate_id, sequence);

CREATE INDEX IF NOT EXISTS idx_events_aggregate_id
    ON events (aggregate_id);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    runtime TEXT NOT NULL,
    metadata TEXT NOT NULL CHECK (json_valid(metadata)),
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aggregates (
    aggregate_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    last_sequence INTEGER NOT NULL,
    snapshot TEXT NOT NULL CHECK (json_valid(snapshot)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
""",
    ),
)


class EventStore:
    """SQLite-backed event store.

    Normal mode creates the database and applies migrations. Read-only mode opens
    exactly with ``file:<path>?mode=ro`` and refuses write operations.
    """

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).expanduser()
        self.read_only = read_only
        self._connection = self._connect()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object | None,
    ) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the configured SQLite connection for low-level checks."""
        return self._connection

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(
                f"file:{self.path}?mode=ro",
                uri=True,
                timeout=_SQLITE_TIMEOUT_SECONDS,
                isolation_level=None,
            )
            self._configure_connection(connection, allow_journal_change=False)
            self._assert_migrations_present(connection)
            return connection

        self._prepare_filesystem()
        connection = sqlite3.connect(
            self.path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        self._set_db_file_mode()
        self._configure_connection(connection, allow_journal_change=True)
        self._apply_migrations(connection)
        self._ensure_bootstrap_event(connection)
        return connection

    def _prepare_filesystem(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=_DB_DIR_MODE)
        os.chmod(self.path.parent, _DB_DIR_MODE)

    def _set_db_file_mode(self) -> None:
        if self.path.exists():
            os.chmod(self.path, _DB_FILE_MODE)

    def _configure_connection(
        self,
        connection: sqlite3.Connection,
        *,
        allow_journal_change: bool,
    ) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        if allow_journal_change:
            self._execute_with_lock_retry(connection, "PRAGMA journal_mode=WAL")
        else:
            connection.execute("PRAGMA journal_mode")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        for migration in MIGRATIONS:
            row = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if row is None:
                # sqlite3.Connection.executescript manages transaction state itself.
                # The SQL is idempotent so it is safe to rerun after a missing row.
                connection.executescript(migration.sql)
                connection.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (migration.version, iso8601_utc_now()),
                )

    def _ensure_bootstrap_event(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT 1 FROM events WHERE aggregate_id = ? AND sequence = 1",
            ("mobius.bootstrap",),
        ).fetchone()
        if row is not None:
            return

        created_at = iso8601_utc_now()
        payload = _canonical_json({"schema_version": max(m.version for m in MIGRATIONS)})
        with self._immediate_transaction(connection):
            connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_id, aggregate_id, sequence, type, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "mobius-bootstrap-v1",
                    "mobius.bootstrap",
                    1,
                    "mobius.bootstrap",
                    payload,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO aggregates(aggregate_id, type, last_sequence, snapshot, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(aggregate_id) DO UPDATE SET
                    type = excluded.type,
                    last_sequence = MAX(aggregates.last_sequence, excluded.last_sequence),
                    updated_at = excluded.updated_at
                """,
                ("mobius.bootstrap", "mobius.bootstrap", 1, "{}", created_at),
            )

    def _assert_migrations_present(self, connection: sqlite3.Connection) -> None:
        connection.execute("SELECT version, applied_at FROM schema_migrations LIMIT 1").fetchall()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run write operations in a BEGIN IMMEDIATE transaction and flush WAL on exit."""
        self._ensure_writable()
        with self._immediate_transaction(self._connection):
            yield self._connection
        self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    @contextlib.contextmanager
    def _immediate_transaction(self, connection: sqlite3.Connection) -> Iterator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> EventRecord:
        """Append an event idempotently and return the persisted row.

        If ``sequence`` is omitted, it is allocated as ``MAX(sequence)+1`` for
        the aggregate inside a ``BEGIN IMMEDIATE`` transaction.
        """
        self._ensure_writable()
        payload_json = _canonical_json(payload)
        new_event_id = event_id or str(uuid.uuid4())
        with self.transaction() as connection:
            next_sequence = sequence or self._next_sequence(connection, aggregate_id)
            created_at = iso8601_utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_id, aggregate_id, sequence, type, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_event_id,
                    aggregate_id,
                    next_sequence,
                    event_type,
                    payload_json,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO aggregates(aggregate_id, type, last_sequence, snapshot, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(aggregate_id) DO UPDATE SET
                    type = excluded.type,
                    last_sequence = MAX(aggregates.last_sequence, excluded.last_sequence),
                    updated_at = excluded.updated_at
                """,
                (aggregate_id, event_type, next_sequence, "{}", created_at),
            )
            row = connection.execute(
                """
                SELECT event_id, aggregate_id, sequence, type, payload, created_at
                FROM events
                WHERE aggregate_id = ? AND sequence = ?
                """,
                (aggregate_id, next_sequence),
            ).fetchone()
        if row is None:
            msg = "append did not return a persisted event"
            raise RuntimeError(msg)
        return _event_from_row(row)

    def create_session(
        self,
        session_id: str,
        *,
        runtime: str,
        metadata: Mapping[str, Any] | None = None,
        status: str = "started",
    ) -> None:
        """Create a session row idempotently."""
        self._ensure_writable()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO sessions(
                    session_id, started_at, ended_at, runtime, metadata, status
                )
                VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (session_id, iso8601_utc_now(), runtime, _canonical_json(metadata or {}), status),
            )

    def end_session(self, session_id: str, *, status: str) -> None:
        """Mark a session as ended."""
        self._ensure_writable()
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET ended_at = ?, status = ?
                WHERE session_id = ?
                """,
                (iso8601_utc_now(), status, session_id),
            )

    def read_events(self, aggregate_id: str) -> list[EventRecord]:
        """Read all events for an aggregate in replay order."""
        rows = self._connection.execute(
            """
            SELECT event_id, aggregate_id, sequence, type, payload, created_at
            FROM events
            WHERE aggregate_id = ?
            ORDER BY sequence ASC, event_id ASC
            """,
            (aggregate_id,),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def replay_hash(self, aggregate_id: str) -> str:
        """Return a deterministic SHA-256 hash of an aggregate's event stream."""
        digest = hashlib.sha256()
        for event in self.read_events(aggregate_id):
            digest.update(
                _canonical_json(
                    {
                        "aggregate_id": event.aggregate_id,
                        "sequence": event.sequence,
                        "type": event.type,
                        "payload": json.loads(event.payload),
                    }
                ).encode("utf-8")
            )
        return digest.hexdigest()

    def integrity_check(self) -> str:
        """Run SQLite's integrity check."""
        value = self._connection.execute("PRAGMA integrity_check").fetchone()
        return str(value[0]) if value is not None else ""

    def _next_sequence(self, connection: sqlite3.Connection, aggregate_id: str) -> int:
        value = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE aggregate_id = ?",
            (aggregate_id,),
        ).fetchone()
        return int(value[0])

    def _execute_with_lock_retry(self, connection: sqlite3.Connection, sql: str) -> None:
        deadline = time.monotonic() + _SQLITE_TIMEOUT_SECONDS
        while True:
            try:
                connection.execute(sql)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _ensure_writable(self) -> None:
        if self.read_only:
            msg = "event store is open in read-only mode"
            raise PermissionError(msg)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _event_from_row(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        event_id=str(row["event_id"]),
        aggregate_id=str(row["aggregate_id"]),
        sequence=int(row["sequence"]),
        type=str(row["type"]),
        payload=str(row["payload"]),
        created_at=str(row["created_at"]),
    )
