"""Handlers for the Mobius lineage command."""

from __future__ import annotations

from typing import NoReturn

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.lineage import (
    LineageNode,
    LineageOutput,
    build_lineage,
    replay_hash_for_aggregate,
)


def run(
    context: CliContext,
    aggregate_id: str | None = None,
    *,
    aggregate: str | None = None,
    json_output: bool = False,
    hash_output: bool = False,
) -> None:
    """Print lineage or a deterministic replay hash for an aggregate."""
    selected_id = aggregate or aggregate_id
    if selected_id is None:
        output.write_error_line("lineage requires an id")
        raise SystemExit(int(ExitCode.USAGE))

    paths = get_paths(context.mobius_home)
    if hash_output:
        replay_hash = replay_hash_for_aggregate(paths.event_store, selected_id)
        if replay_hash is None:
            _raise_not_found(selected_id)
        output.write_line(replay_hash)
        return

    lineage = build_lineage(paths.event_store, selected_id)
    if lineage is None:
        _raise_not_found(selected_id)
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(lineage, text=_markdown_lines(lineage))


def _markdown_lines(lineage: LineageOutput) -> list[str]:
    lines = [f"# Lineage {lineage.aggregate_id}", "", "## Tree"]
    root_depth = min(_ancestor_depths(lineage))
    depth_offset = max(0, -root_depth)
    root_nodes = [node for node in lineage.ancestors if node.depth == root_depth]
    if root_nodes:
        _append_node(
            lines,
            root_nodes[0],
            current_id=lineage.current.aggregate_id,
            depth_offset=depth_offset,
        )
        for node in lineage.ancestors[1:]:
            _append_node(
                lines,
                node,
                current_id=lineage.current.aggregate_id,
                depth_offset=depth_offset,
            )
    _append_node(
        lines,
        lineage.current,
        current_id=lineage.current.aggregate_id,
        depth_offset=depth_offset,
    )
    for node in lineage.descendants:
        _append_node(
            lines,
            node,
            current_id=lineage.current.aggregate_id,
            depth_offset=depth_offset,
        )
    lines.extend(
        [
            "",
            "## Current",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Aggregate | `{lineage.current.aggregate_id}` |",
            f"| Runtime | `{lineage.current.runtime}` |",
            f"| Status | `{lineage.current.status}` |",
            f"| Phase | `{lineage.current.phase}` |",
        ]
    )
    return lines


def _append_node(
    lines: list[str],
    node: LineageNode,
    *,
    current_id: str,
    depth_offset: int,
) -> None:
    indent = "  " * max(node.depth + depth_offset, 0)
    label = node.runtime.capitalize()
    marker = " *(current)*" if node.aggregate_id == current_id else ""
    parent = f" parent=`{node.parent_id}`" if node.parent_id else ""
    lines.append(
        f"{indent}- {label} `{node.aggregate_id}` phase=`{node.phase}` "
        f"status=`{node.status}`{parent}{marker}"
    )


def _ancestor_depths(lineage: LineageOutput) -> list[int]:
    return [node.depth for node in lineage.ancestors] or [0]


def _raise_not_found(aggregate_id: str) -> NoReturn:
    output.write_error_line(f"lineage not found: {aggregate_id}")
    raise SystemExit(int(ExitCode.NOT_FOUND))
