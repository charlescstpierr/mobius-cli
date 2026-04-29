"""Typer command registration for Mobius v3a."""

from __future__ import annotations

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
        resume: Annotated[
            bool,
            typer.Option("--resume", help="Resume from the next incomplete build phase."),
        ] = False,
    ) -> None:
        run_build(
            ctx.obj,
            intent=intent,
            interactive=interactive,
            wizard=wizard,
            agent=agent,
            resume=resume,
        )


def run_build(
    context: Any,
    *,
    intent: str | None,
    interactive: bool = True,
    wizard: bool = False,
    agent: bool = False,
    resume: bool = False,
) -> None:
    """Execute the v3a four-phase build router."""
    from mobius.persistence.event_store import EventStore
    from mobius.v3a import load_runtime_config
    from mobius.v3a.interview.runner import run_interview
    from mobius.v3a.interview.scribe import run_seed_handoff
    from mobius.v3a.phase_router.resume import ResumeUsageError, latest_resume_point
    from mobius.v3a.phase_router.router import (
        BuildLockError,
        PhaseResult,
        PhaseRouter,
        build_process_lock,
        wizard_countdown_from_env,
    )
    from mobius.workflow.ids import readable_session_id

    resolved_intent = (intent or "").strip()
    if not resolved_intent and interactive and not agent and not wizard:
        import sys

        if sys.stdin.isatty():
            resolved_intent = typer.prompt("What do you want to build?").strip()
    if not resolved_intent:
        resolved_intent = "tiny TODO CLI"

    run_id = readable_session_id("build", resolved_intent)
    config = load_runtime_config(Path.cwd())
    run_dir = config.build_dir / run_id
    event_store_path = config.build_dir / "events.db"
    mode = _mode(interactive=interactive, wizard=wizard, agent=agent)

    # Register projections lazily when the command actually runs.
    import importlib

    importlib.import_module("mobius.v3a.projections.interview_projection")
    importlib.import_module("mobius.v3a.projections.phase_projection")

    artifacts: dict[str, Any] = {"intent": resolved_intent, "run_id": run_id}
    try:
        with build_process_lock(context.mobius_home), EventStore(event_store_path) as store:
            start_phase_key = "interview"
            if resume:
                resume_point = latest_resume_point(store)
                run_id = resume_point.run_id
                start_phase_key = resume_point.next_phase
                run_dir = config.build_dir / run_id
                artifacts.update(resume_point.artifacts)
                artifacts.update(
                    {
                        "run_id": run_id,
                        "resume_from": resume_point.completed_phase,
                    }
                )
            store.create_session(
                run_id,
                runtime="build",
                metadata={"mode": mode},
                status="running",
            )

            def interview_phase(_phase: Any) -> PhaseResult:
                store.append_event(
                    run_id,
                    "interview.llm_call_started",
                    {
                        "agents": ["socrate", "avocat", "architecte"],
                        "intent": resolved_intent,
                    },
                )
                result = run_interview(
                    intent=resolved_intent,
                    run_id=run_id,
                    output_dir=run_dir,
                    auto_confirm=True,
                )
                artifacts.update(
                    {
                        "transcript": str(result.transcript_path),
                        "fixture": str(result.fixture_path),
                        "turns": result.turns,
                        "ambiguity_score": result.ambiguity_score,
                        "max_component": result.max_component,
                        "human_confirmed": result.human_confirmed,
                    }
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
                    {
                        "turn": result.turns,
                        "convergence_exempt": result.socrate_proposed_done,
                    },
                )
                return PhaseResult(
                    summary=(
                        f"Wrote fixture.yaml and transcript.md after {result.turns} turns "
                        f"(ambiguity {result.ambiguity_score:.2f})."
                    ),
                    payload=dict(artifacts),
                    turn=result.turns,
                    ambiguity_score=result.ambiguity_score,
                    converged_proposed=result.socrate_proposed_done,
                )

            def seed_phase(_phase: Any) -> PhaseResult:
                fixture = Path(str(artifacts["fixture"]))
                seed_result = run_seed_handoff(
                    fixture_path=fixture,
                    workspace=config.workspace,
                )
                artifacts.update(
                    {
                        "spec_yaml": str(seed_result.spec_path),
                        "backup": (
                            str(seed_result.backup_path)
                            if seed_result.backup_path is not None
                            else None
                        ),
                        "seed_command": list(seed_result.command),
                    }
                )
                return PhaseResult(
                    summary="Generated spec.yaml v2 via mobius interview --non-interactive.",
                    payload=dict(artifacts),
                )

            def maturity_phase(_phase: Any) -> PhaseResult:
                artifacts.update(
                    {
                        "maturity_status": "pending_f05",
                        "maturity_report": str(run_dir / "maturity-report.md"),
                    }
                )
                return PhaseResult(
                    summary="Reserved maturity gate output for F05 implementation.",
                    payload=dict(artifacts),
                )

            def scoring_phase(_phase: Any) -> PhaseResult:
                artifacts.update(
                    {
                        "score_status": "pending_f06",
                        "score_json": str(run_dir / "score.json"),
                    }
                )
                store.end_session(run_id, status="completed")
                return PhaseResult(
                    summary="Reserved score.json and delivery handoff for F06/F08.",
                    payload=dict(artifacts),
                )

            router = PhaseRouter(
                run_id=run_id,
                event_sink=store,
                mode=mode,
                wizard_countdown_seconds=wizard_countdown_from_env(),
            )
            router.run(
                {
                    "interview": interview_phase,
                    "seed": seed_phase,
                    "maturity": maturity_phase,
                    "scoring": scoring_phase,
                },
                start_phase_key=start_phase_key,
            )
    except ResumeUsageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except BuildLockError as exc:
        raise typer.Exit(code=6) from exc


def _mode(*, interactive: bool, wizard: bool, agent: bool) -> str:
    if agent:
        return "agent"
    if wizard:
        return "wizard"
    if interactive:
        return "interactive"
    return "interactive"
