"""Handler for the Mobius ac-tree command."""

from __future__ import annotations

from typing import NoReturn

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.ac_tree import ACTreeNode, ACTreeOutput, build_ac_tree
from mobius.workflow.run import mark_stale_run_if_needed


def run(
    context: CliContext,
    run_id: str,
    *,
    json_output: bool = False,
    cursor: int = 0,
    max_nodes: int = 50,
) -> None:
    """Print a compact acceptance-criteria tree for ``run_id``."""
    paths = get_paths(context.mobius_home)
    mark_stale_run_if_needed(paths, run_id)
    tree = build_ac_tree(
        paths.event_store,
        run_id,
        cursor=cursor,
        max_nodes=max_nodes,
    )
    if tree is None:
        _raise_not_found(run_id)
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(tree, text=_markdown_lines(tree))


def _markdown_lines(tree: ACTreeOutput) -> list[str]:
    lines = [
        f"# AC Tree {tree.run_id}",
        "",
        f"- State: `{tree.state}`",
        f"- Cursor: `{tree.cursor}`",
    ]
    if tree.truncated:
        lines.append(f"- Truncated: `{tree.omitted_nodes}` omitted nodes")
    lines.append("")

    children_by_source: dict[str, list[tuple[str, str]]] = {}
    for edge in tree.edges:
        children_by_source.setdefault(edge.source, []).append((edge.target, edge.relation))
    node_by_id = {node.id: node for node in tree.nodes}
    _append_node(
        lines,
        tree.nodes[0],
        node_by_id,
        children_by_source,
        depth=0,
        seen=set(),
    )
    return lines


def _append_node(
    lines: list[str],
    node: ACTreeNode,
    node_by_id: dict[str, ACTreeNode],
    children_by_source: dict[str, list[tuple[str, str]]],
    *,
    depth: int,
    seen: set[str],
) -> None:
    if node.id in seen:
        return
    seen.add(node.id)
    suffix = ""
    if node.sequence is not None:
        suffix = f" `seq={node.sequence}`"
    elif node.state is not None:
        suffix = f" `state={node.state}`"
    lines.append(f"{'  ' * depth}- {node.label}{suffix}")
    for child_id, _relation in children_by_source.get(node.id, []):
        child = node_by_id.get(child_id)
        if child is not None:
            _append_node(
                lines,
                child,
                node_by_id,
                children_by_source,
                depth=depth + 1,
                seen=seen,
            )


def _raise_not_found(run_id: str) -> NoReturn:
    output.write_error_line(f"run not found: {run_id}")
    raise SystemExit(int(ExitCode.NOT_FOUND))
