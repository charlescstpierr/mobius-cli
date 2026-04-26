import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from mobius.persistence.event_store import EventStore


def test_sigkill_during_write_recovers_with_integrity_ok(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    marker_path = tmp_path / "started"
    project_src = Path(__file__).resolve().parents[3] / "src"
    child_code = f"""
from pathlib import Path
import time

from mobius.persistence.event_store import EventStore

db_path = Path({str(db_path)!r})
marker_path = Path({str(marker_path)!r})
with EventStore(db_path) as store:
    marker_path.write_text("ready")
    for index in range(10_000):
        store.append_event("crash-aggregate", "worker.event", {{"index": index}})
        time.sleep(0.001)
"""

    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        env={**os.environ, "PYTHONPATH": str(project_src)},
    )
    deadline = time.monotonic() + 5
    while not marker_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert marker_path.exists()
    process.send_signal(signal.SIGKILL)
    process.wait(timeout=5)

    with EventStore(db_path) as store:
        partial_rows = store.connection.execute(
            "SELECT count(*) FROM events WHERE payload IS NULL OR payload = ''"
        ).fetchone()
        sequences = [
            row[0]
            for row in store.connection.execute(
                "SELECT sequence FROM events WHERE aggregate_id = ? ORDER BY sequence",
                ("crash-aggregate",),
            ).fetchall()
        ]
        assert store.integrity_check() == "ok"

    assert partial_rows[0] == 0
    assert sequences == list(range(1, len(sequences) + 1))

    read_only_connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        read_only_integrity = read_only_connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        read_only_connection.close()
    assert read_only_integrity[0] == "ok"
