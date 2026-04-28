"""Handler for the ``mobius hud`` command."""

from __future__ import annotations

import json

from mobius.cli import output
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
    if context.json_output or json_output:
        output.write_json(summary.model_dump_json())
        return
    _write_markdown(summary)


def _write_markdown(summary: HudSummary) -> None:
    output.write_line("# Mobius HUD")
    output.write_line("")
    output.write_line("## Current Spec")
    output.write_line(f"- Goal: {summary.spec.goal}")
    output.write_line(f"- Owner: {summary.spec.owner}")
    output.write_line(f"- Grade: {summary.spec.grade}")
    output.write_line("")
    output.write_line("## Latest Run")
    output.write_line(f"- ID: {summary.latest_run.id}")
    output.write_line(f"- Title: {summary.latest_run.title}")
    output.write_line(f"- Status: {summary.latest_run.status}")
    output.write_line(f"- Duration: {summary.latest_run.duration}")
    output.write_line("")
    output.write_line("## Criteria")
    output.write_line("| Criterion | Verdict | Commands |")
    output.write_line("| --- | --- | --- |")
    for criterion in summary.criteria:
        commands = ", ".join(json.dumps(command) for command in criterion.commands) or "—"
        output.write_line(f"| {criterion.label} | {criterion.verdict} | {commands} |")
    if not summary.criteria:
        output.write_line("| — | unverified | — |")
    output.write_line("")
    output.write_line("## Next Recommended Command")
    output.write_line(summary.next_recommended_command or "No unverified criterion has a command.")
    output.write_line("")
    output.write_line("## Proofs")
    output.write_line(f"- Collected: {summary.proofs_collected}")
    output.write_line(f"- Last QA: {summary.last_qa_timestamp}")
    if summary.stale:
        output.write_line("")
        output.write_line("Projection cache is stale; run `mobius projection rebuild`.")
