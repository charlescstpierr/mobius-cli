"""Handler for the Mobius qa command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.workflow.qa import QAReport, evaluate_run_qa
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

    if context.json_output or json_output:
        output.write_json(report.model_dump_json())
    else:
        _write_markdown(report)

    if report.summary.failed:
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))


def _write_markdown(report: QAReport) -> None:
    output.write_line(f"# QA {report.run_id}")
    output.write_line("")
    output.write_line(f"- Mode: `{report.mode}`")
    output.write_line(f"- State: `{report.state}`")
    output.write_line(f"- Total checks: `{report.summary.total}`")
    output.write_line(f"- Failed checks: `{report.summary.failed}`")
    output.write_line("")
    output.write_line("| Check | Result | Detail |")
    output.write_line("| --- | --- | --- |")
    for result in report.results:
        verdict = "pass" if result.passed else "fail"
        output.write_line(f"| {result.label} | {verdict} | {result.detail} |")
