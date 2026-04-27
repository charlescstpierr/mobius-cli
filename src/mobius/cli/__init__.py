"""CLI entry point exports with fast paths for release latency budgets."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from mobius import __version__

_TERMINAL_STATES = frozenset({"completed", "failed", "crashed", "cancelled", "interrupted"})
# Latest applied SQLite schema version. Kept in sync with mobius.persistence.event_store.MIGRATIONS.
_LATEST_SCHEMA_VERSION = 1


def main() -> None:
    """Run Mobius, using lightweight fast paths before importing Typer/Rich."""
    argv = sys.argv[1:]
    if _try_fast_path(argv):
        return

    from mobius.cli.main import main as typer_main

    typer_main()


def _try_fast_path(argv: list[str]) -> bool:
    if argv in (["--help"], ["-h"]):
        _write_fast_help()
        return True
    if argv == ["--version"]:
        sys.stdout.write(f"mobius {__version__}\n")
        return True
    if _try_fast_store_status(argv):
        return True
    return bool(_try_fast_status(argv))


def _write_fast_help() -> None:
    sys.stdout.write(
        """Usage: mobius [OPTIONS] COMMAND [ARGS]...

Fast, MCP-free workflow CLI.

Options:
  --json     Emit machine-readable JSON for commands that support structured output.
  --version  Show the Mobius version and exit.
  -h, --help Show this message and exit.

Commands:
  init       Scaffold a new Mobius workspace at PATH.
  interview  Run the project interview and produce a spec.
  seed       Create a seed session from a project spec or interview session.
  run        Execute a Mobius seed spec.
  status     Show Mobius event-store status.
  ac-tree    Print a compact acceptance-criteria tree for a run.
  qa         Run deterministic QA checks for a Mobius run.
  cancel     Cancel a detached Mobius run.
  evolve     Run a Mobius generation evolution loop.
  lineage    Print an aggregate lineage tree or replay hash.
  setup      Install or remove Mobius agent integration assets.
  config     Show, get, and set Mobius configuration.
"""
    )


def _try_fast_store_status(argv: list[str]) -> bool:
    """Fast path for ``mobius status`` with no run id (store-level status).

    This path avoids importing rich, pydantic, and workflow modules. It only
    runs when the schema_migrations table already contains the latest version,
    so the slow path (which applies migrations) is still reached on first
    invocation or when the migrations row is missing.
    """
    json_output = False
    remaining = list(argv)
    if remaining and remaining[0] == "--json":
        json_output = True
        remaining.pop(0)
    if remaining != ["status"] and remaining != ["status", "--json"]:
        return False
    options = remaining[1:]
    if "--json" in options:
        json_output = True
        options.remove("--json")
    if options:
        return False

    mobius_home = Path(os.environ.get("MOBIUS_HOME", str(Path.home() / ".mobius"))).expanduser()
    db_path = mobius_home / "events.db"

    if not db_path.exists():
        # Bootstrap the store inline so first-run still hits the fast budget.
        try:
            _fast_bootstrap_store(mobius_home, db_path)
        except (OSError, sqlite3.Error):
            return False

    try:
        connection = _connect(db_path, read_only=True)
    except sqlite3.Error:
        return False
    try:
        try:
            row = connection.execute(
                "SELECT count(*) FROM schema_migrations WHERE version = ?",
                (_LATEST_SCHEMA_VERSION,),
            ).fetchone()
        except sqlite3.Error:
            return False
        if row is None or int(row[0]) == 0:
            return False
        migration_count = connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
        event_count = connection.execute("SELECT count(*) FROM events").fetchone()
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()

    integrity_check = str(integrity_row[0]) if integrity_row is not None else ""
    migrations_applied = int(migration_count[0]) > 0
    payload = {
        "event_store": str(db_path),
        "read_only": False,
        "migrations_applied": migrations_applied,
        "integrity_check": integrity_check,
        "event_count": int(event_count[0]),
    }
    if json_output:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return True
    sys.stdout.write(
        f"event_store={payload['event_store']}\n"
        f"read_only={str(payload['read_only']).lower()}\n"
        f"migrations_applied={str(payload['migrations_applied']).lower()}\n"
        f"integrity_check={payload['integrity_check']}\n"
        f"event_count={payload['event_count']}\n"
    )
    return True


def _try_fast_status(argv: list[str]) -> bool:
    json_output = False
    remaining = list(argv)
    if remaining and remaining[0] == "--json":
        json_output = True
        remaining.pop(0)
    if not remaining or remaining[0] != "status":
        return False
    options = remaining[1:]
    if "--follow" in options or "--read-only" in options or "-h" in options or "--help" in options:
        return False
    if "--json" in options:
        json_output = True
        options.remove("--json")
    if len(options) != 1 or options[0].startswith("-"):
        return False

    run_id = options[0]
    mobius_home = Path(os.environ.get("MOBIUS_HOME", str(Path.home() / ".mobius"))).expanduser()
    db_path = mobius_home / "events.db"
    if not db_path.exists():
        _raise_fast_not_found(run_id)

    _mark_stale_session_if_needed(mobius_home, db_path, run_id)
    try:
        with _connect(db_path, read_only=True) as connection:
            row = connection.execute(
                """
                SELECT session_id, started_at, status
                FROM sessions
                WHERE session_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                _raise_fast_not_found(run_id)
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
    except sqlite3.Error as exc:
        sys.stderr.write(f"status failed: {exc}\n")
        raise SystemExit(1) from exc

    last_event_at = str(event["created_at"] if event is not None else row["started_at"])
    payload = {
        "run_id": str(row["session_id"]),
        "state": str(row["status"]),
        "started_at": str(row["started_at"]),
        "last_event_at": last_event_at,
    }
    if json_output:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return True
    sys.stdout.write(
        f"# Run {payload['run_id']}\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| State | {payload['state']} |\n"
        f"| Started at | {payload['started_at']} |\n"
        f"| Last event at | {payload['last_event_at']} |\n"
    )
    return True


def _mark_stale_session_if_needed(mobius_home: Path, db_path: Path, session_id: str) -> None:
    run_pid_file = mobius_home / "runs" / session_id / "pid"
    evolution_pid_file = mobius_home / "evolutions" / session_id / "pid"
    pid_file = evolution_pid_file if evolution_pid_file.exists() else run_pid_file
    if not pid_file.exists():
        return

    with _connect(db_path, read_only=False) as connection:
        session = connection.execute(
            "SELECT runtime, status FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        runtime = (
            str(session["runtime"])
            if session is not None
            else ("evolution" if pid_file == evolution_pid_file else "run")
        )
        if session is not None and str(session["status"]) in _TERMINAL_STATES:
            _cleanup_pid_file(pid_file)
            return
        pid = _read_pid(pid_file)
        if pid is not None and _pid_is_live(pid):
            return
        _cleanup_pid_file(pid_file)
        if session is None:
            _create_session(
                connection,
                session_id,
                runtime,
                {"reason": "stale pid file", "pid": pid},
            )
        _append_event(
            connection,
            session_id,
            f"{runtime}.crashed",
            {"reason": "stale pid file", "pid": pid},
        )
        ended_at = _iso8601_utc_now()
        connection.execute(
            "UPDATE sessions SET ended_at = ?, status = ? WHERE session_id = ?",
            (ended_at, "crashed", session_id),
        )


_FAST_BOOTSTRAP_SQL = """
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
"""


def _fast_bootstrap_store(mobius_home: Path, db_path: Path) -> None:
    """Create the event store and apply the initial migration without imports."""
    mobius_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(mobius_home, 0o700)
    connection = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    try:
        os.chmod(db_path, 0o600)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(_FAST_BOOTSTRAP_SQL)
        applied_at = _iso8601_utc_now()
        connection.execute(
            "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (_LATEST_SCHEMA_VERSION, applied_at),
        )
        payload = json.dumps(
            {"schema_version": _LATEST_SCHEMA_VERSION},
            sort_keys=True,
            separators=(",", ":"),
        )
        connection.execute("BEGIN IMMEDIATE")
        try:
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
                    applied_at,
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
                ("mobius.bootstrap", "mobius.bootstrap", 1, "{}", applied_at),
            )
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
    finally:
        connection.close()


def _connect(db_path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=30.0,
            isolation_level=None,
        )
    else:
        connection = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _create_session(
    connection: sqlite3.Connection,
    session_id: str,
    runtime: str,
    metadata: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO sessions(session_id, started_at, ended_at, runtime, metadata, status)
        VALUES (?, ?, NULL, ?, ?, ?)
        """,
        (session_id, _iso8601_utc_now(), runtime, _canonical_json(metadata), "running"),
    )


def _append_event(
    connection: sqlite3.Connection,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, object],
) -> None:
    sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE aggregate_id = ?",
        (aggregate_id,),
    ).fetchone()[0]
    created_at = _iso8601_utc_now()
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
            _canonical_json(payload),
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


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _iso8601_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _read_pid(pid_file: Path) -> int | None:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_pid_file(pid_file: Path) -> None:
    with suppress(FileNotFoundError):
        pid_file.unlink()


def _raise_fast_not_found(run_id: str) -> NoReturn:
    sys.stderr.write(f"run not found: {run_id}\n")
    raise SystemExit(4)


__all__ = ["main"]
