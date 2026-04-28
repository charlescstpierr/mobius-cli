import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.persistence.event_store import EventRecord, EventStore
from mobius.persistence.projections import (
    ProjectionUpdater,
    apply_projections,
    load_projection_snapshot,
    register_projection,
    unregister_projection,
)


class BrokenUpdater:
    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        raise RuntimeError(f"cannot project {event.type}")


class CountingUpdater:
    def update_snapshot(
        self,
        event: EventRecord,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = dict(current_snapshot)
        snapshot["count"] = int(snapshot.get("count", 0)) + 1
        snapshot["last"] = event.type
        return snapshot


def _snapshot(store: EventStore) -> dict[str, Any]:
    return load_projection_snapshot(store.connection)


def test_broken_projection_marks_stale(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    previous: ProjectionUpdater | None = register_projection("broken.", BrokenUpdater())
    try:
        with EventStore(db_path) as store:
            event = store.append_event("agg-1", "broken.event", {"value": 1})
            snapshot = _snapshot(store)
    finally:
        if previous is None:
            unregister_projection("broken.")
        else:
            register_projection("broken.", previous)

    assert snapshot["stale"] is True
    assert "RuntimeError" in snapshot["stale_reason"]
    assert snapshot["stale_since_event_id"] == event.event_id


def test_event_persisted_when_projection_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "events.db"
    previous: ProjectionUpdater | None = register_projection("broken.", BrokenUpdater())
    try:
        with EventStore(db_path) as store:
            event = store.append_event("agg-1", "broken.event", {"value": 1})
        with EventStore(db_path, read_only=True) as store:
            events = store.read_events("agg-1")
            snapshot = _snapshot(store)
    finally:
        if previous is None:
            unregister_projection("broken.")
        else:
            register_projection("broken.", previous)

    assert [persisted.event_id for persisted in events] == [event.event_id]
    assert events[0].payload_data == {"value": 1}
    assert snapshot["stale"] is True


def test_rebuild_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event("run-1", "run.started", {"goal": "Ship", "title": "Ship"})
        store.append_event(
            "run-1",
            "qa.proof_collected",
            {"criterion_ref": "C1", "exit_code": 0, "timed_out": False},
        )

    monkeypatch.setenv("MOBIUS_HOME", str(home))
    runner = CliRunner()
    first = runner.invoke(app, ["projection", "rebuild", "--json"], catch_exceptions=False)
    with EventStore(db_path, read_only=True) as store:
        first_snapshot = _snapshot(store)
    second = runner.invoke(app, ["projection", "rebuild", "--json"], catch_exceptions=False)
    with EventStore(db_path, read_only=True) as store:
        second_snapshot = _snapshot(store)
        rebuild_events = [
            event
            for event in store.read_events("mobius.projection.rebuilds")
            if event.type == "projection.rebuilt"
        ]

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first_snapshot == second_snapshot
    assert len(rebuild_events) == 2
    assert json.loads(first.stdout)["events_replayed"] == 3
    assert json.loads(second.stdout)["events_replayed"] == 4


def test_freshness_for_each_event_type() -> None:
    registry = {
        "qa.": CountingUpdater(),
        "spec.": CountingUpdater(),
        "run.": CountingUpdater(),
    }
    snapshot: dict[str, Any] = {}
    for index, event_type in enumerate(
        ("qa.proof_collected", "spec.grade_assigned", "run.started"),
        start=1,
    ):
        event = EventRecord(
            event_id=f"event-{index}",
            aggregate_id="agg-1",
            sequence=index,
            type=event_type,
            payload="{}",
            created_at=f"2026-04-28T00:00:0{index}.000000Z",
        )
        snapshot = apply_projections(event, snapshot, registry=registry)

    assert snapshot == {"count": 3, "last": "run.started"}


def test_projection_cli_rebuild_from_event_requires_existing_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    with EventStore(home / "events.db"):
        pass
    monkeypatch.setenv("MOBIUS_HOME", str(home))

    result = CliRunner().invoke(
        app,
        ["projection", "rebuild", "--from-event", "missing"],
        catch_exceptions=False,
    )

    assert result.exit_code == 4
    assert "event not found" in result.stderr
