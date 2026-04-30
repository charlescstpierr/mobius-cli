"""Handler for the ``mobius hud`` command."""

from __future__ import annotations

import json

from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext
from mobius.config import get_paths
from mobius.workflow.hud import HudSummary, load_hud


def run(
    context: CliContext,
    *,
    json_output: bool = False,
) -> None:
    """Render the projection-backed Mobius HUD."""
    paths = get_paths(context.mobius_home)
    result = load_hud(paths.event_store)
    summary = result.summary
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(summary, text=_markdown_lines(summary))


def _markdown_lines(summary: HudSummary) -> list[str]:
    lines = [
        "# Mobius HUD",
        "",
        "## Current Spec",
        f"- Goal: {summary.spec.goal}",
        f"- Owner: {summary.spec.owner}",
        f"- Grade: {summary.spec.grade}",
        "",
        "## Latest Run",
        f"- ID: {summary.latest_run.id}",
        f"- Title: {summary.latest_run.title}",
        f"- Status: {summary.latest_run.status}",
        f"- Duration: {summary.latest_run.duration}",
        "",
        "## Criteria",
        "| Criterion | Verdict | Commands |",
        "| --- | --- | --- |",
    ]
    for criterion in summary.criteria:
        commands = ", ".join(json.dumps(command) for command in criterion.commands) or "—"
        lines.append(f"| {criterion.label} | {criterion.verdict} | {commands} |")
    if not summary.criteria:
        lines.append("| — | unverified | — |")
    lines.extend(
        [
            "",
            "## Next Recommended Command",
            summary.next_recommended_command or "No unverified criterion has a command.",
            "",
            "## Proofs",
            f"- Collected: {summary.proofs_collected}",
            f"- Last QA: {summary.last_qa_timestamp}",
        ]
    )
    if summary.stale:
        lines.extend(["", "Projection cache is stale; run `mobius projection rebuild`."])
    return lines
