"""Handler for the Mobius qa command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.qa import QAReport, Verdict, evaluate_run_qa
from mobius.workflow.run import mark_stale_run_if_needed


def run(
    context: CliContext,
    run_id: str,
    *,
    offline: bool = True,
    json_output: bool = False,
) -> None:
    """Run deterministic QA checks for ``run_id``."""
    if not offline:
        output.write_error_line("qa currently supports offline mode only")
        raise typer.Exit(code=int(ExitCode.VALIDATION))

    paths = get_paths(context.mobius_home)
    mark_stale_run_if_needed(paths, run_id)
    report = evaluate_run_qa(paths.event_store, run_id)
    if report is None:
        output.write_error_line(f"run not found: {run_id}")
        raise typer.Exit(code=int(ExitCode.NOT_FOUND))

    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(report, text=lambda: _write_markdown(report))

    if report.summary.global_verdict == Verdict.FAIL:
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))


def _write_markdown(report: QAReport) -> None:
    output.write_line(f"# QA {report.run_id}")
    output.write_line("")
    output.write_line(f"- Mode: `{report.mode}`")
    output.write_line(f"- State: `{report.state}`")
    output.write_line(f"- Total checks: `{report.summary.total}`")
    output.write_line(f"- Passed checks: `{report.summary.passed}`")
    output.write_line(f"- Failed checks: `{report.summary.failed}`")
    output.write_line(f"- Unverified checks: `{report.summary.unverified}`")
    output.write_line(f"- Global verdict: `{report.summary.global_verdict.value}`")
    output.write_line("")
    output.write_line("| Check | Result | Detail |")
    output.write_line("| --- | --- | --- |")
    for result in report.results:
        output.write_line(f"| {result.label} | {result.verdict.value} | {result.detail} |")
