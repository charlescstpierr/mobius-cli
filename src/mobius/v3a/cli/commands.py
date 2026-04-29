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
        force_immature: Annotated[
            bool,
            typer.Option("--force-immature", help="Override the Phase 3 maturity gate."),
        ] = False,
        auto_top_up: Annotated[
            bool,
            typer.Option("--auto-top-up", help="Deterministically top up spec maturity."),
        ] = False,
        override_reason: Annotated[
            str | None,
            typer.Option("--override-reason", help="Reason recorded with --force-immature."),
        ] = None,
    ) -> None:
        run_build(
            ctx.obj,
            intent=intent,
            interactive=interactive,
            wizard=wizard,
            agent=agent,
            resume=resume,
            force_immature=force_immature,
            auto_top_up=auto_top_up,
            override_reason=override_reason,
        )


def run_build(
    context: Any,
    *,
    intent: str | None,
    interactive: bool = True,
    wizard: bool = False,
    agent: bool = False,
    resume: bool = False,
    force_immature: bool = False,
    auto_top_up: bool = False,
    override_reason: str | None = None,
) -> None:
    """Execute the v3a four-phase build router."""
    from mobius.persistence.event_store import EventStore
    from mobius.v3a import load_runtime_config
    from mobius.v3a.interview.runner import run_interview
    from mobius.v3a.interview.scribe import run_seed_handoff
    from mobius.v3a.maturity.scorer import (
        MaturityGateError,
        render_report,
        score_spec,
        top_up_spec_to_threshold,
    )
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
    importlib.import_module("mobius.v3a.projections.audit_projection")
    importlib.import_module("mobius.v3a.projections.scoring_projection")

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
                spec_path = Path(str(artifacts.get("spec_yaml") or config.workspace / "spec.yaml"))
                if auto_top_up:
                    top_up = top_up_spec_to_threshold(spec_path)
                    report = top_up.after
                    artifacts.update(
                        {
                            "maturity_top_up_questions": top_up.questions_asked,
                            "maturity_score_before_top_up": top_up.before.score,
                        }
                    )
                else:
                    report = score_spec(spec_path)
                report_path = run_dir / "maturity-report.md"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(render_report(report), encoding="utf-8")
                artifacts.update(
                    {
                        "maturity_status": "passed" if report.passed else "blocked",
                        "maturity_score": report.score,
                        "maturity_breakdown": dict(report.breakdown),
                        "maturity_report": str(report_path),
                    }
                )
                if not report.passed:
                    if not force_immature:
                        raise MaturityGateError(report)
                    reason = _override_reason(override_reason)
                    override_payload = {
                        "reason": reason,
                        "maturity_score": report.score,
                        "threshold": 0.8,
                        "spec_yaml": str(spec_path),
                    }
                    store.append_event(run_id, "human.overrode", override_payload)
                    store.append_event(run_id, "spec.maturity_overridden", override_payload)
                    artifacts["maturity_status"] = "overridden"
                    artifacts["maturity_override_reason"] = reason
                return PhaseResult(
                    summary=(
                        f"Maturity {report.score:.2f} — "
                        f"{artifacts['maturity_status']}."
                    ),
                    payload=dict(artifacts),
                    ambiguity_score=report.score,
                )

            def scoring_phase(_phase: Any) -> PhaseResult:
                from mobius.v3a.phase_router.handoff import run_auto_handoff
                from mobius.v3a.scoring.engine import ScoreInputs, compute_score

                spec_path = Path(str(artifacts.get("spec_yaml") or config.workspace / "spec.yaml"))
                score_path = run_dir / "score.json"
                score = compute_score(
                    ScoreInputs(
                        spec=spec_path,
                        run_id=run_id,
                        ambiguity_score=(
                            float(artifacts["ambiguity_score"])
                            if "ambiguity_score" in artifacts
                            else None
                        ),
                        artifacts=dict(artifacts),
                    ),
                    event_sink=store,
                )
                score.write_json(score_path)
                artifacts.update(
                    {
                        "score_status": "computed",
                        "score_out_of_10": score.score_out_of_10,
                        "score_json": str(score_path),
                    }
                )
                handoff = run_auto_handoff(spec_path=spec_path, output_dir=run_dir)
                artifacts.update(
                    {
                        "handoff_agent": handoff.agent,
                        "handoff_prompt": str(handoff.prompt_path),
                        "handoff_copied_to_clipboard": handoff.copied_to_clipboard,
                        "handoff_clipboard_tool": handoff.clipboard_tool,
                        "handoff_command": list(handoff.command),
                        "handoff_display": handoff.display,
                    }
                )
                store.end_session(run_id, status="completed")
                return PhaseResult(
                    summary=(
                        f"Computed score {score.score_out_of_10}/10, wrote score.json, "
                        "and rendered the agent handoff prompt."
                    ),
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
    except MaturityGateError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(render_report(exc.report), err=True)
        raise typer.Exit(code=1) from exc


def _mode(*, interactive: bool, wizard: bool, agent: bool) -> str:
    if agent:
        return "agent"
    if wizard:
        return "wizard"
    if interactive:
        return "interactive"
    return "interactive"


def _override_reason(reason: str | None) -> str:
    if reason is not None and reason.strip():
        return reason.strip()
    import sys

    if sys.stdin.isatty():
        return str(typer.prompt("Why override the maturity gate?")).strip()
    return "non-interactive --force-immature override"


def run_maturity(context: Any, *, spec: Path, json_output: bool = False) -> None:
    """Read-only standalone maturity inspection command."""
    from mobius.v3a.maturity.scorer import render_report, score_spec

    _ = context
    report = score_spec(spec)
    if json_output:
        import json

        typer.echo(json.dumps(report.to_dict(), sort_keys=True))
        return
    typer.echo(render_report(report))
