"""Deterministic v3a interview runner used by ``mobius build``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mobius.v3a.interview.architecte import propose_options
from mobius.v3a.interview.avocat import Avocat, DeterministicAvocat
from mobius.v3a.interview.budget_tracker import BudgetTracker, InterviewBudget
from mobius.v3a.interview.socrate import Keystroke, parse_keystroke, propose_question
from mobius.v3a.interview.transcript import TranscriptTurn, TranscriptWriter

if TYPE_CHECKING:
    from mobius.workflow.interview import InterviewFixture


@dataclass(frozen=True)
class InterviewRunResult:
    """Artifacts produced by the v3a interview phase."""

    run_id: str
    transcript_path: Path
    fixture_path: Path
    fixture: InterviewFixture
    turns: int
    ambiguity_score: float
    max_component: float
    socrate_proposed_done: bool
    human_confirmed: bool
    usd_spent: float


def run_interview(
    *,
    intent: str,
    run_id: str,
    output_dir: Path,
    answers: list[str] | None = None,
    auto_confirm: bool = True,
    budget_tracker: InterviewBudget | None = None,
    avocat: Avocat | None = None,
) -> InterviewRunResult:
    """Run the deterministic three-agent interview loop."""
    from mobius.workflow.interview import compute_ambiguity_score

    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "transcript.md"
    fixture_path = output_dir / "fixture.yaml"
    transcript = TranscriptWriter(transcript_path)
    budget = BudgetTracker() if budget_tracker is None else budget_tracker
    avocat_adapter = DeterministicAvocat() if avocat is None else avocat
    human_answers = answers or _default_answers(intent)
    justifications: list[str] = []
    constraints: list[str] = []
    success: list[str] = []
    fixture = _fixture_for_turn(intent, constraints=constraints, success=success)
    socrate_proposed = False
    human_confirmed = False

    for turn_index, answer in enumerate(human_answers, start=1):
        parsed = parse_keystroke(answer)
        if parsed is not None:
            if parsed.kind in {Keystroke.STOP, Keystroke.ENOUGH}:
                human_confirmed = True
                break
            if parsed.kind is Keystroke.RESTART:
                constraints.clear()
                success.clear()
                justifications.clear()
                continue
        _apply_answer(answer, constraints=constraints, success=success)
        fixture = _fixture_for_turn(intent, constraints=constraints, success=success)
        score = compute_ambiguity_score(fixture)
        convergence_ready = score.score < 0.2 and max(score.components.values()) < 0.4
        socrate = propose_question(
            turn_index,
            justifications,
            convergence_ready=convergence_ready,
        )
        if socrate.lemma_check is not None and not socrate.lemma_check.passed:
            # The fallback in Socrate should prevent this in normal operation,
            # but blocked turns are simply not recorded as successful rationales.
            pass
        else:
            justifications.append(socrate.because)
        socrate_proposed = socrate.proposes_done
        human_confirmed = bool(auto_confirm and socrate.proposes_done)
        avocat_statement = avocat_adapter.inject_edge_case(turn_index, intent)
        options = propose_options(intent, turn_index)
        transcript.append_turn(
            TranscriptTurn(
                turn=turn_index,
                socrate=socrate.question,
                because=socrate.because,
                human=answer,
                avocat=avocat_statement.statement,
                architecte=tuple(f"{option.name}: {option.trade_off}" for option in options),
            )
        )
        budget.record_mock_turn()
        if convergence_ready and socrate_proposed and human_confirmed:
            break

    score = compute_ambiguity_score(fixture)
    _write_fixture(fixture_path, fixture)
    return InterviewRunResult(
        run_id=run_id,
        transcript_path=transcript_path,
        fixture_path=fixture_path,
        fixture=fixture,
        turns=len(justifications),
        ambiguity_score=score.score,
        max_component=max(score.components.values(), default=1.0),
        socrate_proposed_done=socrate_proposed,
        human_confirmed=human_confirmed,
        usd_spent=budget.usd_spent,
    )


def _fixture_for_turn(
    intent: str, *, constraints: list[str], success: list[str]
) -> InterviewFixture:
    from mobius.workflow.interview import InterviewFixture

    return InterviewFixture(
        project_type="greenfield",
        goal=_goal_from_intent(intent),
        constraints=list(constraints) or ["Respect the user's stated product intent."],
        success=list(success) or ["A working implementation can be verified end-to-end."],
        context="",
        template="cli" if "cli" in intent.lower() or "todo" in intent.lower() else "blank",
    )


def _goal_from_intent(intent: str) -> str:
    text = intent.strip() or "Build a small useful product from an interactive brief."
    if len(text.split()) < 5:
        return f"Build {text} with clear behavior and verifiable outcomes."
    return text


def _default_answers(intent: str) -> list[str]:
    noun = "TODO CLI" if "todo" in intent.lower() else "product"
    return [
        f"Ship the first usable {noun} workflow.",
        "Primary entrypoint is a command-line command with deterministic output.",
        "Keep state local, avoid network services, and preserve clear error messages.",
        "Empty input returns a helpful validation error instead of silent success.",
        "End-to-end test creates one item, lists it, completes it, and verifies output.",
        "Support a small vocabulary: add, list, done, empty, duplicate, malformed.",
        ":enough",
    ]


def _apply_answer(answer: str, *, constraints: list[str], success: list[str]) -> None:
    lowered = answer.lower()
    if lowered.startswith(":"):
        return
    if any(word in lowered for word in ("avoid", "preserve", "keep", "must", "never")):
        constraints.append(answer)
    elif any(word in lowered for word in ("test", "verify", "success", "output")):
        success.append(answer)
    else:
        success.append(f"Product behavior includes: {answer}")


def _write_fixture(path: Path, fixture: InterviewFixture) -> None:
    project_type = str(fixture.project_type)
    goal = str(fixture.goal)
    constraints = [str(item) for item in fixture.constraints]
    success = [str(item) for item in fixture.success]
    context = str(fixture.context)
    template = str(fixture.template)
    lines = [
        f"project_type: {_yaml_scalar(project_type)}",
        f"goal: {_yaml_scalar(goal)}",
        "constraints:",
        *[f"  - {_yaml_scalar(item)}" for item in constraints],
        "success:",
        *[f"  - {_yaml_scalar(item)}" for item in success],
        f"context: {_yaml_scalar(context)}",
        f"template: {_yaml_scalar(template)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    if any(character in value for character in ":#[]{}&*!|>'\"%@`"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
