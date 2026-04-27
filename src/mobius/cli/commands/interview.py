"""Handler for the Mobius interview command."""

from __future__ import annotations

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
)


class InterviewOutput(BaseModel):
    """Structured output for a completed interview."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    output: str
    ambiguity_score: float
    ambiguity_gate: float
    passed_gate: bool


def run(
    context: CliContext,
    *,
    non_interactive: bool = False,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> None:
    """Run a deterministic non-interactive interview and write a project spec."""
    if not non_interactive:
        output.write_error_line("interactive interview requires an LLM and is not implemented yet")
        raise typer.Exit(code=int(ExitCode.VALIDATION))
    if input_path is None:
        output.write_error_line("--input is required with --non-interactive")
        raise typer.Exit(code=int(ExitCode.USAGE))
    if output_path is None:
        output.write_error_line("--output is required with --non-interactive")
        raise typer.Exit(code=int(ExitCode.USAGE))

    try:
        fixture = parse_fixture(input_path)
        score = compute_ambiguity_score(fixture)
        score.raise_for_gate()
    except (AmbiguityGateError, ValueError) as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc

    session_id = f"interview_{uuid.uuid4().hex[:12]}"
    paths = get_paths(context.mobius_home)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spec_yaml = render_spec_yaml(session_id, fixture, score)

    with EventStore(paths.event_store) as store:
        store.create_session(
            session_id,
            runtime="interview",
            metadata={
                "mode": "non-interactive",
                "input": str(input_path),
                "output": str(output_path),
            },
            status="running",
        )
        store.append_event(
            session_id,
            "interview.started",
            {
                "mode": "non-interactive",
                "input": str(input_path),
                "project_type": fixture.project_type,
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
            },
        )
        store.end_session(session_id, status="completed")

    payload = InterviewOutput(
        session_id=session_id,
        output=str(output_path),
        ambiguity_score=score.score,
        ambiguity_gate=score.threshold,
        passed_gate=score.passed,
    )
    if context.json_output:
        output.write_json(payload.model_dump_json())
        return
    output.write_line(f"session_id={payload.session_id}")
    output.write_line(f"output={payload.output}")
    output.write_line(f"ambiguity_score={payload.ambiguity_score}")
