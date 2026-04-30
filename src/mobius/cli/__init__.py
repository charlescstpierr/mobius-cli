"""CLI entry point exports with fast paths for release latency budgets."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, NoReturn, cast

if TYPE_CHECKING:
    from pathlib import Path
    from sqlite3 import Connection as SQLiteConnection


class _LazyModuleProxy:
    def __init__(self, module_name: str) -> None:
        self._module_name = module_name

    def __getattr__(self, name: str) -> Any:
        import importlib

        module = importlib.import_module(self._module_name)
        return getattr(module, name)


sqlite3 = _LazyModuleProxy("sqlite3")

# Latest applied SQLite schema version. Kept in sync with mobius.persistence.event_store.MIGRATIONS.
_LATEST_SCHEMA_VERSION = 1


def main() -> None:
    """Run Mobius, using lightweight fast paths before importing Typer/Rich."""
    argv = sys.argv[1:]
    try:
        if _try_fast_path(argv):
            return

        from mobius.cli.main import main as typer_main

        typer_main()
    except OSError as exc:
        _exit_with_state_dir_error(exc)


def _exit_with_state_dir_error(exc: OSError) -> NoReturn:
    """Translate a state-directory I/O error into a friendly exit message."""
    import os
    from pathlib import Path

    mobius_home = os.environ.get("MOBIUS_HOME") or str(Path.home() / ".mobius")
    reason = exc.strerror or exc.__class__.__name__
    sys.stderr.write(
        f"cannot create Mobius state directory at {mobius_home}: {reason}\n"
        "Set MOBIUS_HOME to a writable directory and try again.\n"
    )
    raise SystemExit(1) from exc


def _sqlite3() -> Any:
    return sqlite3


def _try_fast_path(argv: list[str]) -> bool:
    if argv in (["--help"], ["-h"]):
        _write_fast_help()
        return True
    if argv == ["--version"]:
        from mobius import __version__

        sys.stdout.write(f"mobius {__version__}\n")
        return True
    if argv == ["cold-start"]:
        _run_fast_cold_start()
        return True
    if _try_fast_hud(argv):
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
  build      Run the v3a Interview Infinie build composer.
  init       Scaffold a new Mobius workspace at PATH.
  interview  Run the project interview and produce a spec.
  seed       Create a seed session from a project spec or interview session.
  run        Execute a Mobius seed spec.
  status     Show Mobius event-store status.
  ac-tree    Print a compact acceptance-criteria tree for a run.
  qa         Run deterministic QA checks for a Mobius run.
  handoff    Render a versioned prompt for a coding agent.
  hud        Show the projection-backed Mobius dashboard.
  cancel     Cancel a detached Mobius run.
  evolve     Run a Mobius generation evolution loop.
  lineage    Print an aggregate lineage tree or replay hash.
  setup      Install or remove Mobius agent integration assets.
  config     Show, get, and set Mobius configuration.
  runs       List runs (and optionally evolutions) recorded in the event store.
  projection Manage the Mobius projection cache.
  cold-start Measure `mobius --help` cold-start median over 5 runs.
"""
    )


def _run_fast_cold_start() -> None:
    """Measure the fast-path ``mobius --help`` median without importing Typer."""
    import os
    import statistics
    import subprocess
    import time

    command = [sys.argv[0], "--help"]
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    samples_ms: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env=env,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise SystemExit(result.returncode)
        samples_ms.append(elapsed_ms)
    median_ms = statistics.median(samples_ms)
    formatted = ", ".join(f"{sample:.1f}" for sample in samples_ms)
    sys.stdout.write(f"cold_start median_ms={median_ms:.1f} samples_ms=[{formatted}]\n")
    if median_ms > 100:
        raise SystemExit(1)


def _try_fast_hud(argv: list[str]) -> bool:
    import json
    import os
    from pathlib import Path

    json_output = False
    remaining = list(argv)
    if remaining and remaining[0] == "--json":
        json_output = True
        remaining.pop(0)
    if not remaining or remaining[0] != "hud":
        return False
    options = remaining[1:]
    if "-h" in options or "--help" in options:
        return False
    if "--json" in options:
        json_output = True
        options.remove("--json")
    if options:
        return False

    mobius_home = Path(os.environ.get("MOBIUS_HOME", str(Path.home() / ".mobius"))).expanduser()
    snapshot: dict[str, object] = {}
    db_path = mobius_home / "events.db"
    if db_path.exists():
        try:
            with _connect(db_path, read_only=True) as connection:
                row = connection.execute(
                    "SELECT snapshot FROM aggregates WHERE aggregate_id = ?",
                    ("mobius.projection.cache",),
                ).fetchone()
        except _sqlite3().Error:
            return False
        if row is not None:
            try:
                parsed = json.loads(str(row["snapshot"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                parsed = {}
            if isinstance(parsed, dict):
                snapshot = parsed

    payload = _fast_hud_payload(snapshot)
    if json_output:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return True
    _write_fast_hud(payload)
    return True


def _fast_hud_payload(snapshot: dict[str, object]) -> dict[str, object]:
    spec = _object_dict(snapshot.get("current_spec"))
    grade = _object_dict(snapshot.get("last_grade"))
    latest_run = _object_dict(snapshot.get("latest_run"))
    criteria = _fast_hud_criteria(snapshot)
    return {
        "spec": {
            "goal": _text(spec.get("goal"), "(unknown)"),
            "owner": _owner_text(spec.get("owner")),
            "grade": _text(grade.get("grade"), "ungraded"),
        },
        "latest_run": {
            "id": _text(latest_run.get("id"), "(none)"),
            "title": _text(latest_run.get("title"), "(none)"),
            "status": _text(latest_run.get("status"), "unknown"),
            "duration": _fast_duration(latest_run),
        },
        "criteria": criteria,
        "next_recommended_command": _fast_next_command(criteria),
        "proofs_collected": _int(snapshot.get("proofs_collected")),
        "last_qa_timestamp": _text(snapshot.get("last_qa_timestamp"), "(none)"),
        "stale": bool(snapshot.get("stale", False)),
    }


def _fast_hud_criteria(snapshot: dict[str, object]) -> list[dict[str, object]]:
    raw = snapshot.get("criteria")
    if isinstance(raw, list):
        criteria: list[dict[str, object]] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            commands_raw = item.get("commands")
            commands = (
                [str(command) for command in commands_raw] if isinstance(commands_raw, list) else []
            )
            criteria.append(
                {
                    "id": _text(item.get("id"), f"C{index}"),
                    "label": _text(item.get("label"), _text(item.get("id"), f"Criterion {index}")),
                    "verdict": _text(item.get("verdict"), "unverified").lower(),
                    "commands": commands,
                }
            )
        if criteria:
            return criteria
    summary = _object_dict(snapshot.get("criteria_summary"))
    by_criterion = _object_dict(summary.get("by_criterion"))
    return [
        {"id": str(key), "label": str(key), "verdict": str(value).lower(), "commands": []}
        for key, value in sorted(by_criterion.items())
    ]


def _fast_next_command(criteria: list[dict[str, object]]) -> str | None:
    for criterion in criteria:
        commands = criterion.get("commands")
        if (
            str(criterion.get("verdict", "")).lower() == "unverified"
            and isinstance(commands, list)
            and commands
        ):
            return str(commands[0])
    return None


def _write_fast_hud(payload: dict[str, object]) -> None:
    import json

    spec = _object_dict(payload.get("spec"))
    latest_run = _object_dict(payload.get("latest_run"))
    criteria = payload.get("criteria")
    criteria_rows = criteria if isinstance(criteria, list) else []
    sys.stdout.write(
        "# Mobius HUD\n\n"
        "## Current Spec\n"
        f"- Goal: {spec.get('goal')}\n"
        f"- Owner: {spec.get('owner')}\n"
        f"- Grade: {spec.get('grade')}\n\n"
        "## Latest Run\n"
        f"- ID: {latest_run.get('id')}\n"
        f"- Title: {latest_run.get('title')}\n"
        f"- Status: {latest_run.get('status')}\n"
        f"- Duration: {latest_run.get('duration')}\n\n"
        "## Criteria\n"
        "| Criterion | Verdict | Commands |\n"
        "| --- | --- | --- |\n"
    )
    if criteria_rows:
        for item in criteria_rows:
            if not isinstance(item, dict):
                continue
            commands = item.get("commands")
            command_text = "—"
            if isinstance(commands, list) and commands:
                command_text = ", ".join(json.dumps(str(command)) for command in commands)
            sys.stdout.write(f"| {item.get('label')} | {item.get('verdict')} | {command_text} |\n")
    else:
        sys.stdout.write("| — | unverified | — |\n")
    next_command = payload.get("next_recommended_command")
    sys.stdout.write(
        "\n## Next Recommended Command\n"
        f"{next_command or 'No unverified criterion has a command.'}\n\n"
        "## Proofs\n"
        f"- Collected: {payload.get('proofs_collected')}\n"
        f"- Last QA: {payload.get('last_qa_timestamp')}\n"
    )
    if payload.get("stale"):
        sys.stdout.write("\nProjection cache is stale; run `mobius projection rebuild`.\n")


def _try_fast_store_status(argv: list[str]) -> bool:
    import json
    import os
    from pathlib import Path

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
        except (OSError, _sqlite3().Error):
            return False

    try:
        connection = _connect(db_path, read_only=True)
    except _sqlite3().Error:
        return False
    try:
        try:
            row = connection.execute(
                "SELECT count(*) FROM schema_migrations WHERE version = ?",
                (_LATEST_SCHEMA_VERSION,),
            ).fetchone()
        except _sqlite3().Error:
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
    import json
    import os
    from pathlib import Path

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

    inspector = _fast_session_inspector(mobius_home, db_path)
    try:
        resolved_run_id = inspector.resolve_run_id(run_id)
    except _sqlite3().Error as exc:
        sys.stderr.write(f"status failed: {exc}\n")
        raise SystemExit(1) from exc
    if resolved_run_id is None:
        _raise_fast_not_found(run_id)
    if not isinstance(resolved_run_id, str):
        candidates = ", ".join(resolved_run_id)
        sys.stderr.write(f"ambiguous run prefix: {run_id}; candidates: {candidates}\n")
        raise SystemExit(2)
    run_id = resolved_run_id

    inspector.mark_stale_session_if_needed(run_id)
    try:
        run_status = inspector.read_run_status(run_id)
    except _sqlite3().Error as exc:
        sys.stderr.write(f"status failed: {exc}\n")
        raise SystemExit(1) from exc
    if run_status is None:
        _raise_fast_not_found(run_id)

    payload = run_status.to_payload()
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


def _fast_session_inspector(mobius_home: Path, db_path: Path) -> Any:
    from mobius.cli.session_inspector import SessionInspector, SQLiteSessionAdapter

    return SessionInspector(
        state_dir=mobius_home,
        adapter=SQLiteSessionAdapter(
            db_path,
            connect=lambda path, read_only: _connect(path, read_only=read_only),
            now=_iso8601_utc_now,
            canonical_json=_canonical_json,
        ),
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
    import json
    import os

    mobius_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(mobius_home, 0o700)
    sqlite3 = _sqlite3()
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


def _connect(db_path: Path, *, read_only: bool) -> SQLiteConnection:
    sqlite3 = _sqlite3()
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
    return cast("SQLiteConnection", connection)


def _canonical_json(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _owner_text(value: object) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
        return text or "(none)"
    return _text(value, "(none)")


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _fast_duration(latest_run: dict[str, object]) -> str:
    from datetime import UTC, datetime

    started_at = _text(latest_run.get("started_at"), "")
    ended_at = _text(latest_run.get("ended_at"), "") or _text(latest_run.get("last_event_at"), "")
    if not started_at:
        return "unknown"
    if not ended_at:
        return "running"
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00")).astimezone(UTC)
        ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return "unknown"
    seconds = max(0.0, (ended - started).total_seconds())
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, remaining = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _iso8601_utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _raise_fast_not_found(run_id: str) -> NoReturn:
    sys.stderr.write(f"run not found: {run_id}\n")
    raise SystemExit(4)


#: Stable reference to the package-level entry-point function. The plain
#: ``main`` attribute can be shadowed by the lazily-loaded ``mobius.cli.main``
#: submodule once any code imports it; tests and tooling can rely on
#: ``mobius.cli.entry_point`` to always point at the function.
entry_point = main


__all__ = ["entry_point", "main"]
