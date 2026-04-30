"""Handler for the ``mobius grade`` command."""

from __future__ import annotations

import typer

from mobius.cli.formatter import get_formatter
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
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(report, text=_markdown_lines(report))
    if report.grade != "gold":
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))


def _markdown_lines(report: GoldGradeReport) -> list[str]:
    lines = [
        "# Mobius Grade",
        "",
        f"- Grade: `{report.grade}`",
        f"- Criteria met: `{report.criteria_met}/{report.criteria_total}`",
        "",
        "| Criterion | Result |",
        "| --- | --- |",
    ]
    for key, value in report.details.items():
        lines.append(f"| {key} | {'pass' if value else 'fail'} |")
    return lines
