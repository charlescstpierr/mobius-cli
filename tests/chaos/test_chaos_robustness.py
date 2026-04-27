"""Chaos coverage for SIGKILL-during-fsync, disk-full, race, and migration rollback."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mobius.persistence.event_store import EventStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# --------------------------- SIGKILL-during-append ---------------------------


_KILL_BETWEEN_APPEND_AND_FSYNC_SCRIPT = """
import os
import signal
import sys
from pathlib import Path

from mobius.persistence.event_store import EventStore

db_path = Path(sys.argv[1])

with EventStore(db_path) as store:
    store.append_event("agg-1", "first", {"value": 1})
    store.append_event("agg-1", "second", {"value": 2})
    store.append_event("agg-1", "third", {"value": 3})
    # Pre-fsync: WAL frames written, but checkpoint deferred. Self-SIGKILL
    # before any explicit close to simulate kill -9 between append and fsync.
    sys.stdout.write("READY\\n")
    sys.stdout.flush()
    os.kill(os.getpid(), signal.SIGKILL)
"""


def _hash_events(db_path: Path, aggregate_id: str) -> tuple[str, list[str]]:
    """Return (replay hash, event types) for an aggregate, reopening the DB."""
    with EventStore(db_path) as store:
        events = store.read_events(aggregate_id)
        digest = store.replay_hash(aggregate_id)
    return digest, [event.type for event in events]


def test_sigkill_between_append_and_fsync_preserves_lineage_hash(tmp_path: Path) -> None:
    """Killing -9 mid-append must leave WAL replayable to a stable hash."""
    db_path = tmp_path / "events.db"

    # Run the killer subprocess once to populate the WAL and crash.
    result = subprocess.run(
        [sys.executable, "-c", _KILL_BETWEEN_APPEND_AND_FSYNC_SCRIPT, str(db_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )
    # SIGKILL gives -9 / 137 depending on platform; what matters is non-clean exit.
    assert result.returncode != 0
    assert "READY" in result.stdout

    # Reopen and verify integrity + replay hash determinism across two reopens.
    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"
        events_first = store.read_events("agg-1")
        digest_first = store.replay_hash("agg-1")

    digest_second, types_second = _hash_events(db_path, "agg-1")

    # Either all 3 events committed before the kill, or some prefix did.
    # Whatever survived must produce a deterministic hash on every reopen.
    assert digest_first == digest_second
    assert [event.type for event in events_first] == types_second
    assert len(events_first) >= 1


# ------------------------------- Disk-full --------------------------------


def test_disk_full_during_append_emits_clean_error_no_half_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the SQLite write fails, no partial row survives and the error is clean."""
    db_path = tmp_path / "events.db"

    with EventStore(db_path) as store:
        # Append a normal event first to anchor the aggregate.
        store.append_event("agg-1", "before-disk-full", {"ok": True})

    # Patch _canonical_json so the next append serialization step explodes mid-flight,
    # simulating the OS error envelope a real ENOSPC would surface to Python.
    from mobius.persistence import event_store as event_store_module

    call_state: dict[str, int] = {"explosions": 0}

    def boom(payload: Any) -> str:
        call_state["explosions"] += 1
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(event_store_module, "_canonical_json", boom)

    with EventStore(db_path) as store:
        with pytest.raises(OSError, match="No space left on device"):
            store.append_event("agg-1", "during-disk-full", {"oh": "no"})
        events_after = store.read_events("agg-1")

    # Restore _canonical_json (monkeypatch handles teardown). Reopen to make sure
    # WAL replay does not surface a half-written event.
    monkeypatch.undo()
    with EventStore(db_path) as store:
        events_reopen = store.read_events("agg-1")
        assert store.integrity_check() == "ok"

    types_after = [event.type for event in events_after]
    types_reopen = [event.type for event in events_reopen]
    assert types_after == ["before-disk-full"]
    assert types_reopen == ["before-disk-full"]
    # The patched serialiser explodes at least once when a write is attempted.
    assert call_state["explosions"] >= 1


# ------------------------------ Concurrent run race ------------------------------


def _write_chaos_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Concurrent run race chaos test.
constraints:
  - C1
  - C2
  - C3
success_criteria:
  - S1
  - S2
  - S3
""".strip(),
        encoding="utf-8",
    )


def _run_mobius(*args: str, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def test_two_mobius_run_invocations_share_store_safely(tmp_path: Path) -> None:
    """Two `mobius run` calls racing on the same MOBIUS_HOME must both succeed.

    Per the cross-cutting WAL invariant, the busy_timeout=30000 must let the
    second writer acquire the lock and complete; both detached worker shells
    return exit 0 and a run id. If either ever returned exit 75 ("store busy"),
    we'd rather see it in CI than in production — but that path isn't expected
    here because WAL+busy_timeout is sufficient.
    """
    mobius_home = tmp_path / "home"
    spec = tmp_path / "race.yaml"
    _write_chaos_spec(spec)

    procs = [
        subprocess.Popen(
            ["uv", "run", "mobius", "run", "--spec", str(spec)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=30) for p in procs]

    # Both detached workers must successfully spawn and print run ids.
    rcs = [p.returncode for p in procs]
    run_ids = [out[0].strip() for out in outs]
    assert rcs == [0, 0], f"return codes: {rcs}; stderr: {[o[1] for o in outs]}"
    assert all(run_id.startswith("run_") for run_id in run_ids)
    assert run_ids[0] != run_ids[1]

    # Wait for both detached workers to finish, then audit store integrity.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        pid_files = list((mobius_home / "runs").glob("run_*/pid"))
        if not pid_files:
            break
        time.sleep(0.1)

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        completed_count = connection.execute(
            "SELECT count(*) FROM sessions WHERE status = 'completed'"
        ).fetchone()
    finally:
        connection.close()

    assert integrity[0] == "ok"
    assert completed_count[0] >= 2


# ------------------------- Migration failure rollback -------------------------


def test_failing_migration_rolls_back_and_leaves_no_partial_schema(tmp_path: Path) -> None:
    """A migration that raises mid-script must not leave a partial schema row."""
    from mobius.persistence import event_store as event_store_module

    db_path = tmp_path / "events.db"

    # First, bring up a normal store at version 1.
    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"

    # Inject a failing migration (version 2). The first CREATE succeeds, the
    # second statement is intentionally a syntax error so SQLite raises mid-script.
    bad_migration = event_store_module.Migration(
        version=2,
        sql=(
            "CREATE TABLE failing_v2 (id INTEGER PRIMARY KEY);\n"
            "INSERT INTO this_table_does_not_exist VALUES (1);\n"
        ),
    )

    original_migrations = event_store_module.MIGRATIONS
    try:
        event_store_module.MIGRATIONS = (*original_migrations, bad_migration)
        with pytest.raises(sqlite3.Error):
            EventStore(db_path)
    finally:
        event_store_module.MIGRATIONS = original_migrations

    # Reopen with the original migrations: the schema_migrations table should
    # not list version 2, and integrity_check must still be ok.
    with EventStore(db_path) as store:
        rows = store.connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        integrity = store.integrity_check()

    assert [row["version"] for row in rows] == [1]
    assert integrity == "ok"
