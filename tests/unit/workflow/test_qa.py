import sys
from pathlib import Path

from mobius.persistence.event_store import EventStore
from mobius.workflow.qa import Verdict, assign_silver_grade, evaluate_run_qa
from mobius.workflow.seed import load_seed_spec


def write_spec(
    path: Path,
    *,
    success_criteria: bool = True,
    silver: bool = False,
) -> None:
    success_block = "  - QA returns a passing verdict" if success_criteria else ""
    silver_block = (
        """
non_goals:
  - Do not call an LLM.
owner: qa-team
verification_commands:
  - command: "python -c 'print(1)'"
    criterion_ref: "QA returns a passing verdict"
"""
        if silver
        else ""
    )
    path.write_text(
        f"""
project_type: greenfield
goal: Judge a run without using an LLM.
constraints:
  - Use deterministic offline heuristics
success_criteria:
{success_block}
{silver_block}
""".strip(),
        encoding="utf-8",
    )


def create_completed_run(store_path: Path, run_id: str, spec_path: Path) -> None:
    with EventStore(store_path) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"spec_path": str(spec_path), "project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "Judge a run without using an LLM."})
        store.append_event(run_id, "run.progress", {"step": 1, "total": 1})
        store.append_event(run_id, "run.completed", {"success_criteria_count": 1})
        store.end_session(run_id, status="completed")


def create_failed_run(store_path: Path, run_id: str, spec_path: Path) -> None:
    with EventStore(store_path) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"spec_path": str(spec_path), "project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "Judge a run without using an LLM."})
        store.append_event(run_id, "run.failed", {"reason": "fixture failure"})
        store.end_session(run_id, status="failed")


def test_evaluate_run_qa_passes_completed_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_good", spec)

    report = evaluate_run_qa(store_path, "run_good")

    assert report is not None
    assert report.run_id == "run_good"
    assert report.summary.total == 1
    assert report.summary.failed == 0
    assert report.summary.unverified == 1
    assert report.summary.global_verdict == Verdict.UNVERIFIED
    assert all(result.passed for result in report.results if not result.id.startswith("criterion_"))


def test_evaluate_run_qa_fails_non_completed_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_failed_run(store_path, "run_bad", spec)

    report = evaluate_run_qa(store_path, "run_bad")

    assert report is not None
    assert report.summary.total == 1
    assert report.summary.failed == 0
    assert report.summary.unverified == 1
    assert report.summary.global_verdict == Verdict.FAIL
    failed_ids = {result.id for result in report.results if not result.passed}
    assert "run_completed_successfully" in failed_ids
    assert "no_failure_events" in failed_ids


def test_evaluate_run_qa_returns_none_for_unknown_run(tmp_path: Path) -> None:
    report = evaluate_run_qa(tmp_path / "events.db", "run_missing")

    assert report is None


def test_evaluate_run_qa_uses_event_store_not_spec_file(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_good", spec)
    spec.unlink()

    report = evaluate_run_qa(store_path, "run_good")

    assert report is not None
    assert report.summary.failed == 0
    assert report.summary.unverified == 0
    assert report.summary.global_verdict == Verdict.PASS
    spec_check = next(
        result for result in report.results if result.id == "spec_has_success_criteria"
    )
    assert spec_check.passed is True
    assert spec_check.detail == "success_criteria=1"


def test_assign_silver_grade_requires_every_criterion_linked(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Grade a complete QA-ready spec.
constraints:
  - Keep grading static.
success_criteria:
  - First criterion has proof.
  - B8 - Silver grade is assigned.
non_goals:
  - Do not execute commands for Silver.
owner: alice
verification_commands:
  - command: "true"
    criterion_ref: "First criterion has proof."
  - command: "true"
    criterion_ref: B8
""".strip(),
        encoding="utf-8",
    )

    grade = assign_silver_grade(load_seed_spec(spec))

    assert grade.grade == "silver"
    assert grade.criteria_met == 7
    assert grade.criteria_total == 7
    assert grade.details["all_success_criteria_linked"] is True
    assert grade.details["non_goals_present"] is True
    assert grade.details["owner_present"] is True


def test_assign_silver_grade_demotes_to_bronze_when_static_checks_missing(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Grade an incomplete QA spec.
constraints:
  - Keep grading static.
success_criteria:
  - Criterion lacks a command.
owner: alice
""".strip(),
        encoding="utf-8",
    )

    grade = assign_silver_grade(load_seed_spec(spec))

    assert grade.grade == "bronze"
    assert grade.details["all_success_criteria_linked"] is False
    assert grade.details["non_goals_present"] is False
    assert grade.details["owner_present"] is True


def test_evaluate_run_qa_emits_silver_grade_event(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec, silver=True)
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_silver", spec)

    report = evaluate_run_qa(store_path, "run_silver")

    assert report is not None
    assert report.grade == "silver"
    with EventStore(store_path, read_only=True) as store:
        grade_events = [
            event
            for event in store.read_events("run_silver")
            if event.type == "spec.grade_assigned"
        ]
    assert len(grade_events) == 1
    payload = grade_events[0].payload_data
    assert payload["grade"] == "silver"
    assert payload["criteria_met"] == payload["criteria_total"] == 7


def test_evaluate_run_qa_executes_verification_and_emits_proof(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"""
project_type: greenfield
goal: Collect command proof during QA.
constraints:
  - Keep verification local.
success_criteria:
  - B9
non_goals:
  - Do not call an LLM.
owner: qa-team
verification_commands:
  - command: "{sys.executable} -c 'print(42)'"
    criterion_ref: B9
    timeout_s: 5
""".strip(),
        encoding="utf-8",
    )
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_verify", spec)

    report = evaluate_run_qa(store_path, "run_verify")

    assert report is not None
    assert report.summary.failed == 0
    with EventStore(store_path, read_only=True) as store:
        events = store.read_events("run_verify")
    executed = [event for event in events if event.type == "qa.verification_executed"]
    proofs = [event for event in events if event.type == "qa.proof_collected"]
    assert len(executed) == 1
    assert len(proofs) == 1
    assert executed[0].payload_data["criterion_ref"] == "B9"
    proof_payload = proofs[0].payload_data
    assert proof_payload["criterion_ref"] == "B9"
    assert proof_payload["exit_code"] == 0
    assert proof_payload["stdout"].strip() == "42"


def test_verdict_worst_wins_counts_pass_fail_unverified(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"""
project_type: greenfield
goal: Count ternary criterion verdicts.
constraints:
  - Keep verification local.
success_criteria:
  - pass-criterion
  - fail-criterion
  - unverified-criterion
non_goals:
  - Do not call an LLM.
owner: qa-team
verification_commands:
  - command: "{sys.executable} -c 'import sys; sys.exit(0)'"
    criterion_ref: pass-criterion
  - command: "{sys.executable} -c 'import sys; sys.exit(7)'"
    criterion_ref: fail-criterion
""".strip(),
        encoding="utf-8",
    )
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_ternary", spec)

    report = evaluate_run_qa(store_path, "run_ternary")

    assert report is not None
    assert report.summary.passed == 1
    assert report.summary.failed == 1
    assert report.summary.unverified == 1
    assert report.summary.global_verdict == Verdict.FAIL
    criterion_verdicts = {
        result.label: result.verdict
        for result in report.results
        if result.id.startswith("criterion_")
    }
    assert criterion_verdicts["Criterion 1: pass-criterion"] == Verdict.PASS
    assert criterion_verdicts["Criterion 2: fail-criterion"] == Verdict.FAIL
    assert criterion_verdicts["Criterion 3: unverified-criterion"] == Verdict.UNVERIFIED


def test_criterion_without_verification_command_is_unverified(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_completed_run(store_path, "run_unverified", spec)

    report = evaluate_run_qa(store_path, "run_unverified")

    assert report is not None
    criterion = next(result for result in report.results if result.id == "criterion_1")
    assert criterion.verdict == Verdict.UNVERIFIED
    assert criterion.passed is False
