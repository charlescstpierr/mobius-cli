"""Handler for the Mobius workflow smoke command."""

from __future__ import annotations

import typer

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.workflow.smoke import SmokeReport, run_smoke


def run(
    context: CliContext,
    *,
    json_output: bool = False,
    keep_workspace: bool = False,
) -> None:
    """Execute the offline end-to-end workflow smoke test."""
    report = run_smoke(keep_workspace=keep_workspace)
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(report, text=lambda: _write_markdown(report))
    if not report.passed:
        raise typer.Exit(code=int(ExitCode.GENERIC_ERROR))


def _write_markdown(report: SmokeReport) -> None:
    status = "PASS" if report.passed else "FAIL"
    output.write_line(f"# Workflow smoke: {status}")
    output.write_line("")
    output.write_line(f"- Duration: `{report.duration_ms}ms`")
    output.write_line(f"- Run ID: `{report.run_id or 'unresolved'}`")
    output.write_line(f"- Workspace: `{report.workspace}`")
    output.write_line("")
    output.write_line("| Step | Result | Duration | Detail |")
    output.write_line("| --- | --- | ---: | --- |")
    for step in report.steps:
        result = "pass" if step.passed else "fail"
        output.write_line(
            f"| {step.name} | {result} | {step.duration_ms}ms | {_escape_table(step.detail)} |"
        )


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
