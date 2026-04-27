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
    InterviewFixture,
    compute_ambiguity_score,
    fixture_from_template,
    parse_fixture,
    question_answers,
    render_spec_yaml,
    run_interactive_interview,
)
from mobius.workflow.templates import TEMPLATE_NAMES, detect_template, get_template


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
    project_type: str | None = None,
    goal: str | None = None,
    constraints: list[str] | None = None,
    success_criteria: list[str] | None = None,
    context_value: str | None = None,
) -> None:
    """Run an interview and write a project spec.

    The command supports four modes:

    1. Non-interactive from fixture (``--non-interactive --input <fixture>``):
       reads a deterministic fixture file. Backward compatible.
    2. Non-interactive from CLI flags (``--non-interactive --goal ... \
       --constraint ... --success-criterion ...``): the agent passes
       extracted parameters directly. No fixture file required. Flags
       override fixture values when both are supplied.
    3. Scripted/interactive: prompts on stderr, reads answers from stdin.
       Auto-detects a template from the cwd unless ``--template`` is given.
    4. Re-run from previous spec: not yet supported (out of scope).
    """
    workspace = Path.cwd()
    output_path = output_path or workspace / "spec.yaml"

    try:
        if non_interactive:
            using_flags = any(
                value is not None and value != []
                for value in (goal, constraints, success_criteria, context_value, template)
            )
            if input_path is None and not using_flags:
                output.write_error_line(
                    "non-interactive interview requires --input or --goal/--template; "
                    "see `mobius interview --help`"
                )
                raise typer.Exit(code=int(ExitCode.USAGE))
            fixture = _build_non_interactive_fixture(
                workspace=workspace,
                input_path=input_path,
                template=template,
                project_type=project_type,
                goal=goal,
                constraints=constraints,
                success_criteria=success_criteria,
                context_value=context_value,
            )
        else:
            fixture = run_interactive_interview(
                workspace=workspace,
                template_name=template,
                project_type=project_type or "greenfield",
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


def _build_non_interactive_fixture(
    *,
    workspace: Path,
    input_path: Path | None,
    template: str | None,
    project_type: str | None,
    goal: str | None,
    constraints: list[str] | None,
    success_criteria: list[str] | None,
    context_value: str | None,
) -> InterviewFixture:
    """Build a fixture from a fixture file, CLI flags, or both.

    Resolution order (later wins for non-empty values):

    1. Template defaults — if ``--template`` is given (or auto-detected when
       no fixture and no goal is provided).
    2. Fixture file — when ``--input`` is supplied.
    3. CLI flags (``--goal``, ``--constraint``, ``--success-criterion``,
       ``--context``, ``--project-type``, ``--template``).

    At least one of ``--input``, ``--goal``, or a ``--template`` must be
    supplied so the resulting fixture has a non-trivial goal.
    """
    base = _initial_fixture(
        workspace=workspace,
        input_path=input_path,
        template_name=template,
        project_type=project_type or "greenfield",
    )

    final_template = (template or base.template or "blank").strip().lower() or "blank"
    if final_template not in TEMPLATE_NAMES:
        msg = (
            f"unknown template '{final_template}'. "
            f"Allowed templates: {', '.join(TEMPLATE_NAMES)}"
        )
        raise ValueError(msg)

    final_project_type = (project_type or base.project_type or "greenfield").strip().lower()
    if final_project_type not in {"greenfield", "brownfield"}:
        msg = "project_type must be either 'greenfield' or 'brownfield'"
        raise ValueError(msg)

    final_goal = goal.strip() if goal is not None else base.goal
    final_constraints = (
        [item.strip() for item in constraints if item.strip()]
        if constraints is not None
        else list(base.constraints)
    )
    final_success = (
        [item.strip() for item in success_criteria if item.strip()]
        if success_criteria is not None
        else list(base.success)
    )
    final_context = context_value.strip() if context_value is not None else base.context

    return InterviewFixture(
        project_type=final_project_type,
        goal=final_goal,
        constraints=final_constraints,
        success=final_success,
        context=final_context,
        template=final_template,
    )


def _initial_fixture(
    *,
    workspace: Path,
    input_path: Path | None,
    template_name: str | None,
    project_type: str,
) -> InterviewFixture:
    """Return the starting fixture: from --input, or from a template default."""
    if input_path is not None:
        return parse_fixture(input_path)
    name = template_name or detect_template(workspace)
    return fixture_from_template(get_template(name), project_type=project_type)
