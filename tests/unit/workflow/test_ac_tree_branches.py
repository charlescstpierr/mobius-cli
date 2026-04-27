"""Branch-coverage tests for the ac-tree projection."""

from __future__ import annotations

from pathlib import Path

from mobius.persistence.event_store import EventStore
from mobius.workflow.ac_tree import build_ac_tree


def _completed_run(
    tmp_path: Path, run_id: str, *, status: str = "completed", with_spec: bool = True
) -> Path:
    event_store_path = tmp_path / "events.db"
    spec_path = tmp_path / "spec.yaml"
    if with_spec:
        spec_path.write_text(
            """
project_type: greenfield
goal: AC tree branch test goal.
constraints:
  - C1
  - C2
success_criteria:
  - S1
  - S2
""".strip(),
            encoding="utf-8",
        )
    metadata = {"spec_path": str(spec_path), "project_type": "greenfield"} if with_spec else {}
    with EventStore(event_store_path) as store:
        store.create_session(run_id, runtime="run", metadata=metadata, status="running")
        store.append_event(run_id, "run.started", {"goal": "AC tree branch test goal."})
        store.append_event(run_id, "run.progress", {"step": 1, "total": 2})
        store.append_event(run_id, "run.completed", {"success_criteria_count": 2})
        store.end_session(run_id, status=status)
    return event_store_path


def test_ac_tree_for_unknown_run_returns_none(tmp_path: Path) -> None:
    event_store_path = tmp_path / "events.db"
    with EventStore(event_store_path):
        pass
    assert build_ac_tree(event_store_path, "run_missing") is None


def test_ac_tree_includes_constraints_and_acceptance_criteria(tmp_path: Path) -> None:
    event_store_path = _completed_run(tmp_path, "run_full")
    tree = build_ac_tree(event_store_path, "run_full")
    assert tree is not None
    types = [node.type for node in tree.nodes]
    assert "constraint_group" in types
    assert "acceptance_group" in types
    assert "event_group" in types


def test_ac_tree_truncates_when_max_nodes_exceeded(tmp_path: Path) -> None:
    event_store_path = _completed_run(tmp_path, "run_trunc")
    tree = build_ac_tree(event_store_path, "run_trunc", max_nodes=5)
    assert tree is not None
    assert tree.truncated is True
    assert tree.omitted_nodes > 0
    assert any(node.type == "truncation" for node in tree.nodes)


def test_ac_tree_cursor_filters_event_deltas(tmp_path: Path) -> None:
    event_store_path = _completed_run(tmp_path, "run_cursor")
    full = build_ac_tree(event_store_path, "run_cursor")
    assert full is not None
    cursor_at_end = full.cursor
    bounded = build_ac_tree(event_store_path, "run_cursor", cursor=cursor_at_end)
    assert bounded is not None
    # No event-group when there are no events past the cursor.
    assert not any(node.type == "event_group" for node in bounded.nodes)


def test_ac_tree_failed_state_marks_acceptance_unknown(tmp_path: Path) -> None:
    event_store_path = _completed_run(tmp_path, "run_failed", status="failed")
    tree = build_ac_tree(event_store_path, "run_failed")
    assert tree is not None
    acceptance_states = {node.state for node in tree.nodes if node.type == "acceptance_criterion"}
    assert acceptance_states == {"unknown"}


def test_ac_tree_running_state_marks_acceptance_pending(tmp_path: Path) -> None:
    event_store_path = tmp_path / "events.db"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: pending case
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )
    with EventStore(event_store_path) as store:
        store.create_session(
            "run_pending",
            runtime="run",
            metadata={"spec_path": str(spec)},
            status="running",
        )
        store.append_event("run_pending", "run.started", {"goal": "pending case"})

    tree = build_ac_tree(event_store_path, "run_pending")
    assert tree is not None
    pending = {node.state for node in tree.nodes if node.type == "acceptance_criterion"}
    assert pending == {"pending"}


def test_ac_tree_metadata_only_when_no_spec_no_events(tmp_path: Path) -> None:
    """A run with metadata but no spec_path and no events emits a metadata node."""
    event_store_path = tmp_path / "events.db"
    with EventStore(event_store_path) as store:
        store.create_session(
            "run_meta_only",
            runtime="run",
            metadata={"some_key": "some_value"},
            status="running",
        )

    tree = build_ac_tree(event_store_path, "run_meta_only")
    assert tree is not None
    assert any(node.type == "metadata" for node in tree.nodes)


def test_ac_tree_uses_event_goal_when_spec_missing(tmp_path: Path) -> None:
    event_store_path = tmp_path / "events.db"
    with EventStore(event_store_path) as store:
        store.create_session(
            "run_event_goal",
            runtime="run",
            metadata={"spec_path": "/nonexistent/spec.yaml"},
            status="running",
        )
        store.append_event("run_event_goal", "run.started", {"goal": "Goal from event"})

    tree = build_ac_tree(event_store_path, "run_event_goal")
    assert tree is not None
    goal_nodes = [node for node in tree.nodes if node.type == "goal"]
    assert goal_nodes
    assert "Goal from event" in goal_nodes[0].label
