"""Handler for the Mobius interview command."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.interview import (
    AmbiguityGateError,
    compute_ambiguity_score,
    parse_fixture,
    question_answers,
    render_spec_yaml,
    run_interactive_interview,
)


class InterviewOutput(BaseModel):
    """Structured output for a completed interview."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    output: str
    ambiguity_score: float
    ambiguity_gate: float
    passed_gate: bool
    template: str = "blank"


def run(
    context: CliContext,
    *,
    non_interactive: bool = False,
    input_path: Path | None = None,
    output_path: Path | None = None,
    template: str | None = None,
    project_type: str = "greenfield",
) -> None:
    """Run an interview and write a project spec.

    The command supports three modes:

    1. Non-interactive (``--non-interactive --input <fixture>``): reads a
       deterministic fixture file. Backward compatible.
    2. Scripted/interactive: prompts on stderr, reads answers from stdin.
       Auto-detects a template from the cwd unless ``--template`` is given.
    3. Re-run from previous spec: not yet supported (out of scope).
    """
    workspace = Path.cwd()
    output_path = output_path or workspace / "spec.yaml"

    try:
        if non_interactive:
            if input_path is None:
                output.write_error_line("--input is required with --non-interactive")
                raise typer.Exit(code=int(ExitCode.USAGE))
            fixture = parse_fixture(input_path)
        else:
            fixture = run_interactive_interview(
                workspace=workspace,
                template_name=template,
                project_type=project_type,
            )
        score = compute_ambiguity_score(fixture)
        score.raise_for_gate()
    except (AmbiguityGateError, ValueError) as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc

    session_id = f"interview_{uuid.uuid4().hex[:12]}"
    paths = get_paths(context.mobius_home)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spec_yaml = render_spec_yaml(session_id, fixture, score)

    with EventStore(paths.event_store) as store:
        store.create_session(
            session_id,
            runtime="interview",
            metadata={
                "mode": "non-interactive" if non_interactive else "interactive",
                "input": str(input_path) if input_path else "",
                "output": str(output_path),
                "template": fixture.template,
            },
            status="running",
        )
        store.append_event(
            session_id,
            "interview.started",
            {
                "mode": "non-interactive" if non_interactive else "interactive",
                "input": str(input_path) if input_path else "",
                "project_type": fixture.project_type,
                "template": fixture.template,
            },
        )
        for category, question, answer in question_answers(fixture):
            store.append_event(
                session_id,
                "interview.question_answered",
                {
                    "category": category,
                    "question": question,
                    "answer": answer,
                },
            )
        output_path.write_text(spec_yaml, encoding="utf-8")
        store.append_event(
            session_id,
            "interview.completed",
            {
                "ambiguity_score": score.score,
                "ambiguity_gate": score.threshold,
                "passed_gate": score.passed,
                "output": str(output_path),
                "template": fixture.template,
            },
        )
        store.end_session(session_id, status="completed")

    payload = InterviewOutput(
        session_id=session_id,
        output=str(output_path),
        ambiguity_score=score.score,
        ambiguity_gate=score.threshold,
        passed_gate=score.passed,
        template=fixture.template,
    )
    if context.json_output:
        output.write_json(payload.model_dump_json())
        return
    if not non_interactive:
        sys.stderr.write(f"\n# Wrote {payload.output}\n")
        sys.stderr.flush()
    output.write_line(f"session_id={payload.session_id}")
    output.write_line(f"output={payload.output}")
    output.write_line(f"template={payload.template}")
    output.write_line(f"ambiguity_score={payload.ambiguity_score}")
