import json
from pathlib import Path

from mobius.persistence.event_store import EventStore
from mobius.workflow.ac_tree import build_ac_tree


def write_spec(path: Path, *, success_count: int = 2) -> None:
    success_lines = "\n".join(f"  - Acceptance criterion {index}" for index in range(success_count))
    path.write_text(
        f"""
project_type: greenfield
goal: Build a compact tree.
constraints:
  - Keep stdout data-only
  - Preserve event cursor deltas
success_criteria:
{success_lines}
""".strip(),
        encoding="utf-8",
    )


def create_run(store_path: Path, run_id: str, spec_path: Path) -> None:
    with EventStore(store_path) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"spec_path": str(spec_path), "project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "Build a compact tree."})
        store.append_event(run_id, "run.progress", {"step": 1, "total": 2})
        store.append_event(run_id, "run.progress", {"step": 2, "total": 2})
        store.append_event(run_id, "run.completed", {"success_criteria_count": 2})
        store.end_session(run_id, status="completed")


def test_build_ac_tree_uses_spec_and_events(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_run(store_path, "run_tree", spec)

    tree = build_ac_tree(store_path, "run_tree")

    assert tree is not None
    assert tree.run_id == "run_tree"
    assert tree.state == "completed"
    assert tree.cursor == 4
    labels = {node.label for node in tree.nodes}
    assert "Goal: Build a compact tree." in labels
    assert "Acceptance criterion 1" in labels
    assert "Keep stdout data-only" in labels
    assert any(node.type == "event" and node.sequence == 4 for node in tree.nodes)
    assert any(edge.target == "run_tree:goal" for edge in tree.edges)


def test_build_ac_tree_can_return_cursor_delta_events(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_run(store_path, "run_tree", spec)

    tree = build_ac_tree(store_path, "run_tree", cursor=2)

    assert tree is not None
    event_sequences = [node.sequence for node in tree.nodes if node.type == "event"]
    assert event_sequences == [3, 4]


def test_build_ac_tree_truncates_large_trees(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec, success_count=20)
    store_path = tmp_path / "events.db"
    create_run(store_path, "run_tree", spec)

    tree = build_ac_tree(store_path, "run_tree", max_nodes=10)

    assert tree is not None
    assert tree.truncated is True
    assert tree.omitted_nodes > 0
    assert len(tree.nodes) == 10
    assert tree.nodes[-1].type == "truncation"
    assert "omitted" in tree.nodes[-1].label


def test_build_ac_tree_json_has_nodes_and_edges(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_run(store_path, "run_tree", spec)

    tree = build_ac_tree(store_path, "run_tree")

    assert tree is not None
    payload = json.loads(tree.model_dump_json())
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["edges"], list)
    assert payload["nodes"]
