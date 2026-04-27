"""Acceptance-criteria tree projection for completed and running Mobius runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventRecord, EventStore
from mobius.workflow.seed import SeedSpec, SeedSpecValidationError, load_seed_spec


class ACTreeNode(BaseModel):
    """One display node in the compact AC tree."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: str
    state: str | None = None
    sequence: int | None = None


class ACTreeEdge(BaseModel):
    """A directed relationship between AC tree nodes."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relation: str


class ACTreeOutput(BaseModel):
    """Structured AC tree output."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: str
    cursor: int
    truncated: bool
    omitted_nodes: int
    nodes: list[ACTreeNode]
    edges: list[ACTreeEdge]


def build_ac_tree(
    event_store_path: Path,
    run_id: str,
    *,
    cursor: int = 0,
    max_nodes: int = 50,
) -> ACTreeOutput | None:
    """Build a compact AC tree projection for ``run_id``.

    ``cursor`` is an event sequence cursor. The stable AC/spec context remains
    visible while event delta nodes are restricted to events with a greater
    sequence, allowing callers to poll efficiently for tree updates.
    """
    bounded_cursor = max(cursor, 0)
    bounded_max_nodes = max(max_nodes, 5)
    with EventStore(event_store_path) as store:
        session = _read_session(store, run_id)
        if session is None:
            return None
        events = store.read_events(run_id)

    state = str(session["status"])
    metadata = _decode_json_object(str(session["metadata"]))
    spec = _load_spec(metadata)
    latest_cursor = max((event.sequence for event in events), default=0)
    nodes, edges = _build_nodes_and_edges(
        run_id=run_id,
        state=state,
        metadata=metadata,
        spec=spec,
        events=[event for event in events if event.sequence > bounded_cursor],
    )
    nodes, edges, omitted_nodes = _truncate(nodes, edges, max_nodes=bounded_max_nodes)
    return ACTreeOutput(
        run_id=run_id,
        state=state,
        cursor=latest_cursor,
        truncated=omitted_nodes > 0,
        omitted_nodes=omitted_nodes,
        nodes=nodes,
        edges=edges,
    )


def _read_session(store: EventStore, run_id: str) -> Any | None:
    return store.connection.execute(
        """
        SELECT session_id, status, metadata
        FROM sessions
        WHERE session_id = ?
        """,
        (run_id,),
    ).fetchone()


def _build_nodes_and_edges(
    *,
    run_id: str,
    state: str,
    metadata: dict[str, Any],
    spec: SeedSpec | None,
    events: list[EventRecord],
) -> tuple[list[ACTreeNode], list[ACTreeEdge]]:
    nodes = [
        ACTreeNode(id=run_id, label=f"Run {run_id}", type="run", state=state),
    ]
    edges: list[ACTreeEdge] = []

    goal = spec.goal if spec is not None else _goal_from_events(events)
    if goal:
        goal_id = f"{run_id}:goal"
        nodes.append(ACTreeNode(id=goal_id, label=f"Goal: {goal}", type="goal", state=state))
        edges.append(ACTreeEdge(source=run_id, target=goal_id, relation="has_goal"))

    constraints = spec.constraints if spec is not None else []
    if constraints:
        _append_group(
            nodes,
            edges,
            root_id=run_id,
            group_id=f"{run_id}:constraints",
            group_label="Constraints",
            group_type="constraint_group",
            child_type="constraint",
            relation="constrains",
            child_labels=constraints,
            child_state="active",
        )

    success_criteria = spec.success_criteria if spec is not None else []
    if success_criteria:
        _append_group(
            nodes,
            edges,
            root_id=run_id,
            group_id=f"{run_id}:acceptance",
            group_label="Acceptance Criteria",
            group_type="acceptance_group",
            child_type="acceptance_criterion",
            relation="accepts",
            child_labels=success_criteria,
            child_state=_criterion_state(state),
        )

    if events:
        deltas_id = f"{run_id}:deltas"
        nodes.append(ACTreeNode(id=deltas_id, label="Event Deltas", type="event_group"))
        edges.append(ACTreeEdge(source=run_id, target=deltas_id, relation="has_delta"))
        for event in events:
            event_id = f"{run_id}:event:{event.sequence}"
            nodes.append(
                ACTreeNode(
                    id=event_id,
                    label=_format_event_label(event),
                    type="event",
                    sequence=event.sequence,
                )
            )
            edges.append(ACTreeEdge(source=deltas_id, target=event_id, relation="emitted"))

    if spec is None and not events and metadata:
        metadata_id = f"{run_id}:metadata"
        nodes.append(ACTreeNode(id=metadata_id, label="Metadata available", type="metadata"))
        edges.append(ACTreeEdge(source=run_id, target=metadata_id, relation="has_metadata"))

    return nodes, edges


def _append_group(
    nodes: list[ACTreeNode],
    edges: list[ACTreeEdge],
    *,
    root_id: str,
    group_id: str,
    group_label: str,
    group_type: str,
    child_type: str,
    relation: str,
    child_labels: list[str],
    child_state: str,
) -> None:
    nodes.append(ACTreeNode(id=group_id, label=group_label, type=group_type))
    edges.append(ACTreeEdge(source=root_id, target=group_id, relation=relation))
    for index, label in enumerate(child_labels, start=1):
        child_id = f"{group_id}:{index}"
        nodes.append(ACTreeNode(id=child_id, label=label, type=child_type, state=child_state))
        edges.append(ACTreeEdge(source=group_id, target=child_id, relation="contains"))


def _truncate(
    nodes: list[ACTreeNode],
    edges: list[ACTreeEdge],
    *,
    max_nodes: int,
) -> tuple[list[ACTreeNode], list[ACTreeEdge], int]:
    if len(nodes) <= max_nodes:
        return nodes, edges, 0

    kept_count = max_nodes - 1
    omitted_nodes = len(nodes) - kept_count
    kept_nodes = nodes[:kept_count]
    root_id = nodes[0].id
    truncation_id = f"{root_id}:truncated"
    kept_nodes.append(
        ACTreeNode(
            id=truncation_id,
            label=f"… {omitted_nodes} nodes omitted (use --max-nodes to expand)",
            type="truncation",
        )
    )
    kept_ids = {node.id for node in kept_nodes}
    kept_edges = [edge for edge in edges if edge.source in kept_ids and edge.target in kept_ids]
    kept_edges.append(ACTreeEdge(source=root_id, target=truncation_id, relation="truncated"))
    return kept_nodes, kept_edges, omitted_nodes


def _load_spec(metadata: dict[str, Any]) -> SeedSpec | None:
    spec_path = metadata.get("spec_path")
    if not isinstance(spec_path, str) or not spec_path:
        return None
    try:
        return load_seed_spec(Path(spec_path))
    except SeedSpecValidationError:
        return None


def _decode_json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _goal_from_events(events: list[EventRecord]) -> str:
    for event in events:
        if event.type == "run.started":
            payload = event.payload_data
            if isinstance(payload, dict) and isinstance(payload.get("goal"), str):
                return str(payload["goal"])
    return ""


def _criterion_state(run_state: str) -> str:
    if run_state == "completed":
        return "satisfied"
    if run_state in {"failed", "crashed", "cancelled", "interrupted"}:
        return "unknown"
    return "pending"


def _format_event_label(event: EventRecord) -> str:
    payload = event.payload_data
    if isinstance(payload, dict) and event.type == "run.progress":
        step = payload.get("step")
        total = payload.get("total")
        return f"seq={event.sequence} {event.type} step={step}/{total}"
    return f"seq={event.sequence} {event.type}"
