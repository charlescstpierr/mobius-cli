from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mobius.persistence.event_store import EventStore


def _append_many(db_path: Path, worker: int, count: int) -> None:
    with EventStore(db_path) as store:
        for index in range(count):
            store.append_event(
                "shared-aggregate",
                "worker.event",
                {"worker": worker, "index": index},
            )


def test_parallel_writers_preserve_contiguous_sequences(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    workers = 5
    per_worker_count = 12

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_append_many, db_path, worker, per_worker_count)
            for worker in range(workers)
        ]
        for future in futures:
            future.result()

    with EventStore(db_path) as store:
        events = store.read_events("shared-aggregate")

    assert [event.sequence for event in events] == list(range(1, workers * per_worker_count + 1))
    assert len({event.event_id for event in events}) == workers * per_worker_count
