import json
from pathlib import Path

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.lineage import build_lineage, replay_hash_for_aggregate


def seed_lineage(home: Path) -> None:
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session(
            "run_root",
            runtime="run",
            metadata={"double_diamond_phase": "deliver"},
            status="completed",
        )
        store.append_event("run_root", "run.started", {"goal": "Build"})
        store.append_event("run_root", "run.completed", {"ok": True})

        store.create_session(
            "evo_child",
            runtime="evolution",
            metadata={"source_run_id": "run_root", "generations": 2},
            status="completed",
        )
        store.append_event("evo_child", "evolution.started", {"source_run_id": "run_root"})

        store.create_session(
            "evo_grandchild",
            runtime="evolution",
            metadata={"source_run_id": "evo_child", "generations": 1},
            status="completed",
        )
        store.append_event("evo_grandchild", "evolution.started", {"source_run_id": "evo_child"})


def test_build_lineage_returns_ancestors_and_descendants(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_lineage(home)

    lineage = build_lineage(get_paths(home).event_store, "evo_child")

    assert lineage is not None
    assert lineage.aggregate_id == "evo_child"
    assert [node.aggregate_id for node in lineage.ancestors] == ["run_root"]
    assert [node.aggregate_id for node in lineage.descendants] == ["evo_grandchild"]
    assert lineage.current.phase == "evolve"
    assert lineage.ancestors[0].phase == "deliver"


def test_build_lineage_returns_none_for_unknown_id(tmp_path: Path) -> None:
    lineage = build_lineage(get_paths(tmp_path / "home").event_store, "missing")

    assert lineage is None


def test_replay_hash_is_deterministic_sha256_for_existing_aggregate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_lineage(home)
    event_store = get_paths(home).event_store

    first = replay_hash_for_aggregate(event_store, "run_root")
    second = replay_hash_for_aggregate(event_store, "run_root")

    assert first is not None
    assert first == second
    assert len(first) == 64
    int(first, 16)


def test_replay_hash_changes_when_aggregate_events_change(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_lineage(home)
    event_store = get_paths(home).event_store
    before = replay_hash_for_aggregate(event_store, "run_root")

    with EventStore(event_store) as store:
        store.append_event("run_root", "run.extra", {"value": "different"})

    after = replay_hash_for_aggregate(event_store, "run_root")

    assert before != after


def test_lineage_json_shape_uses_ancestors_and_descendants_arrays(tmp_path: Path) -> None:
    home = tmp_path / "home"
    seed_lineage(home)

    lineage = build_lineage(get_paths(home).event_store, "evo_child")

    assert lineage is not None
    payload = json.loads(lineage.model_dump_json())
    assert isinstance(payload["ancestors"], list)
    assert isinstance(payload["descendants"], list)
    assert payload["current"]["aggregate_id"] == "evo_child"
