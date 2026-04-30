"""Handler for the Mobius seed command."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict

from mobius.cli import output
from mobius.cli.formatter import get_formatter
from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.ids import readable_session_id
from mobius.workflow.seed import SeedSpecValidationError, assign_bronze_grade, load_seed_spec


class SeedOutput(BaseModel):
    """Structured output for a completed seed."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    source: str
    event_count: int
    grade: str | None = None
    criteria_met: int | None = None
    criteria_total: int | None = None


def run(
    context: CliContext,
    spec_or_session_id: str,
    *,
    json_output: bool = False,
    validate: bool = False,
) -> None:
    """Validate a spec, persist seed events, and emit a seed session id."""
    paths = get_paths(context.mobius_home)
    try:
        spec_path = _resolve_spec_path(paths.event_store, spec_or_session_id)
        spec = load_seed_spec(spec_path)
    except FileNotFoundError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.NOT_FOUND)) from exc
    except SeedSpecValidationError as exc:
        output.write_error_line(str(exc))
        raise typer.Exit(code=int(ExitCode.VALIDATION)) from exc

    session_id = readable_session_id("seed", spec.goal)
    event_count = 0
    with EventStore(paths.event_store) as store:
        store.create_session(
            session_id,
            runtime="seed",
            metadata={
                "source": spec_or_session_id,
                "spec_path": str(spec_path),
                "source_session_id": spec.source_session_id,
            },
            status="running",
        )
        store.append_event(
            session_id,
            "seed.started",
            {
                "source": spec_or_session_id,
                "spec_path": str(spec_path),
                "source_session_id": spec.source_session_id,
            },
        )
        event_count += 1
        store.append_event(
            session_id,
            "seed.validated",
            {
                "project_type": spec.project_type,
                "constraint_count": len(spec.constraints),
                "success_criteria_count": len(spec.success_criteria),
            },
        )
        event_count += 1
        store.append_event(session_id, "seed.completed", spec.to_event_payload())
        event_count += 1
        grade = assign_bronze_grade(spec) if validate else None
        if grade is not None:
            store.append_event(session_id, "spec.grade_assigned", grade.to_event_payload())
            event_count += 1
        store.end_session(session_id, status="completed")

    payload = SeedOutput(
        session_id=session_id,
        source=spec_or_session_id,
        event_count=event_count,
        grade=grade.grade if grade is not None else None,
        criteria_met=grade.criteria_met if grade is not None else None,
        criteria_total=grade.criteria_total if grade is not None else None,
    )
    formatter = get_formatter(context, json_output=json_output)
    formatter.emit(payload, text=payload.session_id)


def _resolve_spec_path(event_store_path: Path, spec_or_session_id: str) -> Path:
    candidate = Path(spec_or_session_id).expanduser()
    if candidate.exists():
        return candidate

    with EventStore(event_store_path) as store:
        events = store.read_events(spec_or_session_id)
    if not events:
        msg = f"seed source not found: {spec_or_session_id}"
        raise FileNotFoundError(msg)

    for event in reversed(events):
        if event.type == "interview.completed":
            output_path = event.payload_data.get("output")
            if isinstance(output_path, str) and output_path:
                path = Path(output_path).expanduser()
                if path.exists():
                    return path
                msg = f"interview spec file not found: {path}"
                raise FileNotFoundError(msg)

    msg = f"session does not contain an interview output spec: {spec_or_session_id}"
    raise SeedSpecValidationError(msg)
