"""Typer command registration for Mobius v3a."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Annotated, Any

import typer


def register(app: typer.Typer) -> None:
    """Register v3a commands into v2's Typer app."""

    @app.command(name="build", help="Run the v3a Interview Infinie build composer.")
    def build_command(
        ctx: typer.Context,
        intent: Annotated[
            str | None,
            typer.Argument(help="Product intent to clarify. Omit for interactive composer."),
        ] = None,
        interactive: Annotated[
            bool,
            typer.Option("--interactive", help="Run with interactive prompts (default mode)."),
        ] = True,
        wizard: Annotated[
            bool,
            typer.Option(
                "--wizard",
                help="Auto-proceed through Phase 1 using deterministic answers.",
            ),
        ] = False,
        agent: Annotated[
            bool,
            typer.Option("--agent", help="Emit JSON suitable for coding-agent orchestration."),
        ] = False,
    ) -> None:
        run_build(
            ctx.obj,
            intent=intent,
            interactive=interactive,
            wizard=wizard,
            agent=agent,
        )


def run_build(
    context: Any,
    *,
    intent: str | None,
    interactive: bool = True,
    wizard: bool = False,
    agent: bool = False,
) -> None:
    """Execute v3a Phase 1 and write transcript + fixture artifacts."""
    from mobius.cli import output
    from mobius.config import get_paths
    from mobius.persistence.event_store import EventStore
    from mobius.v3a import load_runtime_config
    from mobius.v3a.interview.runner import run_interview
    from mobius.workflow.ids import readable_session_id

    # Register projection lazily when the command actually runs.
    importlib.import_module("mobius.v3a.projections.interview_projection")

    resolved_intent = (intent or "").strip()
    if not resolved_intent and interactive and not agent and not wizard:
        resolved_intent = typer.prompt("What do you want to build?").strip()
    if not resolved_intent:
        resolved_intent = "tiny TODO CLI"

    run_id = readable_session_id("build", resolved_intent)
    config = load_runtime_config(Path.cwd())
    run_dir = config.build_dir / run_id
    paths = get_paths(context.mobius_home)

    with EventStore(paths.event_store) as store:
        store.create_session(
            run_id,
            runtime="build",
            metadata={"mode": _mode(interactive=interactive, wizard=wizard, agent=agent)},
            status="running",
        )
        store.append_event(
            run_id,
            "interview.llm_call_started",
            {"agents": ["socrate", "avocat", "architecte"], "intent": resolved_intent},
        )
        result = run_interview(
            intent=resolved_intent,
            run_id=run_id,
            output_dir=run_dir,
            auto_confirm=True,
        )
        store.append_event(
            run_id,
            "interview.llm_call_completed",
            {
                "turns": result.turns,
                "ambiguity_score": result.ambiguity_score,
                "max_component": result.max_component,
            },
        )
        store.append_event(
            run_id,
            "interview.transcript_appended",
            {"turn": result.turns, "transcript": str(result.transcript_path)},
        )
        store.append_event(
            run_id,
            "interview.lemma_check_passed",
            {"turn": result.turns, "convergence_exempt": result.socrate_proposed_done},
        )
        store.end_session(run_id, status="completed")

    payload = {
        "phase_done": "interview",
        "next_phase": "seed",
        "next_command": f"mobius interview --non-interactive --input {result.fixture_path}",
        "run_id": run_id,
        "transcript": str(result.transcript_path),
        "fixture": str(result.fixture_path),
        "turns": result.turns,
        "ambiguity_score": result.ambiguity_score,
        "max_component": result.max_component,
        "converged_proposed": result.socrate_proposed_done,
        "human_confirmed": result.human_confirmed,
    }
    if agent or getattr(context, "json_output", False):
        output.write_line(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    output.write_line(f"run_id={run_id}")
    output.write_line(f"transcript={result.transcript_path}")
    output.write_line(f"fixture={result.fixture_path}")
    output.write_line(f"ambiguity_score={result.ambiguity_score}")
    output.write_line(f"max_component={result.max_component}")


def _mode(*, interactive: bool, wizard: bool, agent: bool) -> str:
    if agent:
        return "agent"
    if wizard:
        return "wizard"
    if interactive:
        return "interactive"
    return "interactive"
