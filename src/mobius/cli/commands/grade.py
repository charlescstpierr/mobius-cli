"""Handler for the ``mobius grade`` command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.grade import GoldGradeReport, evaluate_gold_grade


def run(
    context: CliContext,
    *,
    agent: str = "claude",
    json_output: bool = False,
) -> None:
    """Assign the projection-backed runtime grade."""
    paths = get_paths(context.mobius_home)
    report = evaluate_gold_grade(paths.event_store, agent=agent)
    if context.json_output or json_output:
        output.write_json(report.model_dump_json())
    else:
        _write_markdown(report)
    if report.grade != "gold":
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))


def _write_markdown(report: GoldGradeReport) -> None:
    output.write_line("# Mobius Grade")
    output.write_line("")
    output.write_line(f"- Grade: `{report.grade}`")
    output.write_line(f"- Criteria met: `{report.criteria_met}/{report.criteria_total}`")
    output.write_line("")
    output.write_line("| Criterion | Result |")
    output.write_line("| --- | --- |")
    for key, value in report.details.items():
        output.write_line(f"| {key} | {'pass' if value else 'fail'} |")
