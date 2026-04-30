"""Shared session inspection seam for fast and slow CLI status paths."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})


@dataclass(frozen=True)
class SessionLifecycle:
    """Runtime/status fields needed to inspect a detached session."""

    runtime: str
    status: str


@dataclass(frozen=True)
class RunStatus:
    """Structured status output for a single run."""

    run_id: str
    state: str
    started_at: str
    last_event_at: str

    def to_payload(self) -> dict[str, str]:
        """Return the byte-stable JSON payload shape used by ``mobius status``."""
        return {
            "run_id": self.run_id,
            "state": self.state,
            "started_at": self.started_at,
            "last_event_at": self.last_event_at,
        }


class SessionInspectorAdapter(Protocol):
    """Adapter seam for session data stored behind different implementations."""

    def read_session_lifecycle(self, session_id: str) -> SessionLifecycle | None:
        """Read runtime/status for a session, if present."""

    def record_stale_crash(
        self,
        session_id: str,
        *,
        runtime: str,
        pid: int | None,
        session_exists: bool,
    ) -> None:
        """Persist a synthetic crash for a stale detached worker PID file."""

    def read_run_status(self, run_id: str) -> RunStatus | None:
        """Read run status, if present."""

    def latest_run_id(self) -> str | None:
        """Return the newest run id, if one exists."""

    def run_id_prefix_matches(self, prefix: str) -> Sequence[str]:
        """Return all run ids matching a slug prefix in display order."""


class SessionInspector:
    """Deep module that owns detached-session status and stale-PID semantics."""

    def __init__(self, *, state_dir: Path, adapter: SessionInspectorAdapter) -> None:
        self._state_dir = state_dir
        self._adapter = adapter

    def mark_stale_session_if_needed(self, session_id: str) -> None:
        """Mark a detached run/evolution crashed when its PID file is stale."""
        session = self._adapter.read_session_lifecycle(session_id)
        runtime = (
            session.runtime if session is not None else self._runtime_from_pending_files(session_id)
        )
        if runtime is None:
            return
        pid_file = self._pid_file_for_runtime(session_id, runtime)
        if not pid_file.exists():
            return
        if session is not None and session.status in _TERMINAL_STATES:
            cleanup_pid_file(pid_file)
            return
        pid = read_pid(pid_file)
        if pid is not None and pid_is_live(pid):
            return
        cleanup_pid_file(pid_file)
        self._adapter.record_stale_crash(
            session_id,
            runtime=runtime,
            pid=pid,
            session_exists=session is not None,
        )

    def read_run_status(self, run_id: str) -> RunStatus | None:
        """Read status for a concrete run id."""
        return self._adapter.read_run_status(run_id)

    def resolve_run_id(self, run_id: str) -> str | None | Sequence[str]:
        """Resolve ``latest`` and unique prefixes without dictating CLI exit policy.

        Returns:
            - ``str`` for a resolved run id
            - ``None`` when no run matches
            - ``Sequence[str]`` when a prefix is ambiguous
        """
        if run_id == "latest":
            return self._adapter.latest_run_id()
        if self._adapter.read_run_status(run_id) is not None:
            return run_id
        matches = self._adapter.run_id_prefix_matches(run_id)
        if not matches:
            return None
        if len(matches) > 1:
            return matches
        return matches[0]

    def _runtime_from_pending_files(self, session_id: str) -> str | None:
        if self._pid_file_for_runtime(session_id, "evolution").exists():
            return "evolution"
        if self._pid_file_for_runtime(session_id, "run").exists():
            return "run"
        return None

    def _pid_file_for_runtime(self, session_id: str, runtime: str) -> Path:
        if runtime == "evolution":
            return self._state_dir / "evolutions" / session_id / "pid"
        return self._state_dir / "runs" / session_id / "pid"


class SQLiteSessionAdapter:
    """Direct SQLite adapter used by the import-light CLI fast path."""

    def __init__(
        self,
        db_path: Path,
        *,
        connect: Callable[[Path, bool], Any],
        now: Callable[[], str],
        canonical_json: Callable[[dict[str, object]], str],
    ) -> None:
        self._db_path = db_path
        self._connect = connect
        self._now = now
        self._canonical_json = canonical_json

    def read_session_lifecycle(self, session_id: str) -> SessionLifecycle | None:
        with self._connect(self._db_path, False) as connection:
            row = connection.execute(
                "SELECT runtime, status FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionLifecycle(runtime=str(row["runtime"]), status=str(row["status"]))

    def record_stale_crash(
        self,
        session_id: str,
        *,
        runtime: str,
        pid: int | None,
        session_exists: bool,
    ) -> None:
        payload: dict[str, object] = {"reason": "stale pid file", "pid": pid}
        with self._connect(self._db_path, False) as connection:
            if not session_exists:
                self._create_session(connection, session_id, runtime, payload)
            self._append_event(connection, session_id, f"{runtime}.crashed", payload)
            connection.execute(
                "UPDATE sessions SET ended_at = ?, status = ? WHERE session_id = ?",
                (self._now(), "crashed", session_id),
            )

    def read_run_status(self, run_id: str) -> RunStatus | None:
        with self._connect(self._db_path, True) as connection:
            return _read_run_status_from_connection(connection, run_id)

    def latest_run_id(self) -> str | None:
        with self._connect(self._db_path, True) as connection:
            row = connection.execute(
                """
                SELECT aggregate_id
                FROM events
                WHERE type = 'run.started'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return None if row is None else str(row["aggregate_id"])

    def run_id_prefix_matches(self, prefix: str) -> Sequence[str]:
        with self._connect(self._db_path, True) as connection:
            rows = connection.execute(
                """
                SELECT aggregate_id
                FROM events
                WHERE type = 'run.started'
                  AND aggregate_id LIKE ? ESCAPE '\\'
                ORDER BY created_at DESC, aggregate_id ASC
                """,
                (f"{escape_like(prefix)}%",),
            ).fetchall()
        return [str(row["aggregate_id"]) for row in rows]

    def _create_session(
        self,
        connection: Any,
        session_id: str,
        runtime: str,
        metadata: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO sessions(
                session_id, started_at, ended_at, runtime, metadata, status
            )
            VALUES (?, ?, NULL, ?, ?, ?)
            """,
            (session_id, self._now(), runtime, self._canonical_json(metadata), "running"),
        )

    def _append_event(
        self,
        connection: Any,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        import uuid

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE aggregate_id = ?",
            (aggregate_id,),
        ).fetchone()[0]
        created_at = self._now()
        connection.execute(
            """
            INSERT INTO events(event_id, aggregate_id, sequence, type, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                aggregate_id,
                sequence,
                event_type,
                self._canonical_json(payload),
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
            (aggregate_id, event_type, sequence, "{}", created_at),
        )


class EventStoreSessionAdapter:
    """EventStore adapter used by the Typer command slow path."""

    def __init__(self, event_store_path: Path) -> None:
        self._event_store_path = event_store_path

    def read_session_lifecycle(self, session_id: str) -> SessionLifecycle | None:
        if not self._event_store_path.exists():
            return None
        from mobius.persistence.event_store import EventStore

        with EventStore(self._event_store_path) as store:
            row = store.connection.execute(
                "SELECT runtime, status FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionLifecycle(runtime=str(row["runtime"]), status=str(row["status"]))

    def record_stale_crash(
        self,
        session_id: str,
        *,
        runtime: str,
        pid: int | None,
        session_exists: bool,
    ) -> None:
        from mobius.persistence.event_store import EventStore

        with EventStore(self._event_store_path) as store:
            store.create_session(
                session_id,
                runtime=runtime,
                metadata={"reason": "stale pid file", "pid": pid},
                status="running",
            )
            store.append_event(
                session_id,
                f"{runtime}.crashed",
                {"reason": "stale pid file", "pid": pid},
            )
            store.end_session(session_id, status="crashed")

    def read_run_status(self, run_id: str) -> RunStatus | None:
        from mobius.persistence.event_store import EventStore

        with EventStore(self._event_store_path, read_only=True) as store:
            return _read_run_status_from_connection(store.connection, run_id)

    def latest_run_id(self) -> str | None:
        from mobius.persistence.event_store import EventStore

        with EventStore(self._event_store_path, read_only=True) as store:
            latest = store.get_latest_run()
        return None if latest is None else latest.aggregate_id

    def run_id_prefix_matches(self, prefix: str) -> Sequence[str]:
        from mobius.persistence.event_store import EventStore

        with EventStore(self._event_store_path, read_only=True) as store:
            return [event.aggregate_id for event in store.find_by_slug_prefix(prefix)]


def _read_run_status_from_connection(connection: Any, run_id: str) -> RunStatus | None:
    session = connection.execute(
        """
        SELECT session_id, started_at, ended_at, status
        FROM sessions
        WHERE session_id = ?
        """,
        (run_id,),
    ).fetchone()
    if session is None:
        return None
    event = connection.execute(
        """
        SELECT created_at
        FROM events
        WHERE aggregate_id = ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    last_event_at = str(event["created_at"] if event is not None else session["started_at"])
    return RunStatus(
        run_id=str(session["session_id"]),
        state=str(session["status"]),
        started_at=str(session["started_at"]),
        last_event_at=last_event_at,
    )


def read_pid(pid_file: Path) -> int | None:
    """Read a positive PID from ``pid_file``."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def cleanup_pid_file(pid_file: Path) -> None:
    """Remove a PID file idempotently."""
    with suppress(FileNotFoundError):
        pid_file.unlink()


def pid_is_live(pid: int) -> bool:
    """Return whether ``pid`` currently identifies a live process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def escape_like(value: str) -> str:
    """Escape user input for SQLite ``LIKE … ESCAPE '\\'`` prefix searches."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
