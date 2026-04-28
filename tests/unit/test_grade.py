import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.persistence.event_store import EventStore
from mobius.workflow.grade import evaluate_gold_grade, evaluate_gold_snapshot


def _gold_snapshot() -> dict[str, Any]:
    return {
        "current_spec": {
            "goal": "Ship Gold grading.",
            "constraints": ["Stay projection-backed."],
            "success_criteria": ["C1 - First proof passes.", "C2 - Second proof passes."],
            "verification_commands": [
                {"command": "python -c 'print(1)'", "criterion_ref": "C1"},
                {"command": "python -c 'print(2)'", "criterion_ref": "C2"},
            ],
            "non_goals": ["Do not execute verification commands."],
            "owner": "qa-team",
            "risks": [{"description": "projection drift", "mitigation": "rebuild"}],
        },
        "last_grade": {"grade": "silver"},
        "latest_run": {"id": "run-gold", "status": "completed"},
        "criteria": [
            {"id": "C1", "label": "C1 - First proof passes.", "verdict": "pass"},
            {"id": "C2", "label": "C2 - Second proof passes.", "verdict": "pass"},
        ],
        "criteria_summary": {
            "passed": 2,
            "failed": 0,
            "unverified": 0,
            "by_criterion": {"C1": "pass", "C2": "pass"},
        },
        "proofs_by_criterion": {"C1": 1, "C2": 1},
    }


def test_gold_snapshot_yields_gold() -> None:
    report = evaluate_gold_snapshot(_gold_snapshot())

    assert report.grade == "gold"
    assert report.criteria_met == report.criteria_total == 5
    assert all(report.details.values())


def test_gold_snapshot_demotes_when_one_criterion_fails() -> None:
    snapshot = _gold_snapshot()
    snapshot["criteria"][1]["verdict"] = "fail"
    snapshot["criteria_summary"] = {
        "passed": 1,
        "failed": 1,
        "unverified": 0,
        "by_criterion": {"C1": "pass", "C2": "fail"},
    }

    report = evaluate_gold_snapshot(snapshot)

    assert report.grade == "silver"
    assert report.details["all_success_criteria_passed"] is False


def test_gold_snapshot_requires_one_proof_per_criterion() -> None:
    snapshot = _gold_snapshot()
    snapshot["proofs_by_criterion"] = {"C1": 1}

    report = evaluate_gold_snapshot(snapshot)

    assert report.grade == "silver"
    assert report.details["proof_per_criterion"] is False


def test_gold_snapshot_handles_missing_projection_facts() -> None:
    report = evaluate_gold_snapshot(
        {
            "last_grade": {"grade": "unexpected"},
            "latest_run": {"status": "failed"},
            "criteria": "not-a-list",
            "proofs_by_criterion": "not-a-map",
            "current_spec": {"goal": "", "success_criteria": []},
        }
    )

    assert report.grade == "bronze"
    assert report.details == {
        "silver_grade_present": False,
        "all_success_criteria_passed": False,
        "run_succeeded": False,
        "handoff_dry_run_complete": False,
        "proof_per_criterion": False,
    }


def test_gold_snapshot_accepts_succeeded_status_without_summary() -> None:
    snapshot = _gold_snapshot()
    snapshot["latest_run"] = {"status": "succeeded"}
    snapshot.pop("criteria_summary")
    snapshot["proofs_by_criterion"] = {"C1": 1, "C2": 1}
    snapshot["current_spec"]["constraints"] = []
    snapshot["current_spec"]["agent_instructions"] = {"claude": "Stay focused."}

    report = evaluate_gold_snapshot(snapshot)

    assert report.grade == "gold"
    assert report.details["run_succeeded"] is True
    assert report.details["handoff_dry_run_complete"] is True


def test_gold_snapshot_rejects_unknown_handoff_agent() -> None:
    report = evaluate_gold_snapshot(_gold_snapshot(), agent="unknown")

    assert report.grade == "silver"
    assert report.details["handoff_dry_run_complete"] is False


def test_grade_missing_store_returns_bronze_without_emitting(tmp_path: Path) -> None:
    report = evaluate_gold_grade(tmp_path / "missing.db", emit=False)

    assert report.grade == "bronze"
    assert not (tmp_path / "missing.db").exists()


def test_grade_reads_projection_cache_and_does_not_execute_verification_commands(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        msg = "verification commands must not run during mobius grade"
        raise AssertionError(msg)

    monkeypatch.setattr("mobius.workflow.verify.run_verification", fail_if_called)
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as store:
        store.append_event(
            "seed-gold",
            "seed.completed",
            {
                "goal": "Ship Gold grading.",
                "constraints": ["Stay projection-backed."],
                "success_criteria": ["C1"],
                "verification_commands": [
                    {"command": "python -c 'raise SystemExit(99)'", "criterion_ref": "C1"}
                ],
                "non_goals": ["Do not run commands."],
                "owner": "qa-team",
            },
        )
        store.append_event("seed-gold", "spec.grade_assigned", {"grade": "silver"})
        store.append_event("run-gold", "run.started", {"goal": "Ship", "title": "Ship"})
        store.append_event("run-gold", "run.completed", {"success_criteria_count": 1})
        store.append_event(
            "run-gold",
            "qa.proof_collected",
            {"command": "cached only", "criterion_ref": "C1", "exit_code": 0},
        )

    report = evaluate_gold_grade(db_path)

    assert report.grade == "gold"
    with EventStore(db_path, read_only=True) as store:
        grade_events = [
            event
            for event in store.read_events("mobius.grade")
            if event.type == "spec.grade_assigned"
        ]
    assert grade_events[-1].payload_data["grade"] == "gold"


def test_grade_cli_outputs_json(tmp_path: Path, monkeypatch: Any) -> None:
    home = tmp_path / "home"
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event(
            "seed-gold",
            "seed.completed",
            {
                "goal": "CLI Gold.",
                "constraints": ["Use CLI."],
                "success_criteria": ["C1"],
                "verification_commands": [{"command": "true", "criterion_ref": "C1"}],
                "non_goals": ["No network."],
                "owner": "qa-team",
            },
        )
        store.append_event("seed-gold", "spec.grade_assigned", {"grade": "silver"})
        store.append_event("run-gold", "run.started", {"goal": "CLI Gold", "title": "CLI Gold"})
        store.append_event("run-gold", "run.completed", {"success_criteria_count": 1})
        store.append_event(
            "run-gold",
            "qa.proof_collected",
            {"command": "true", "criterion_ref": "C1", "exit_code": 0},
        )
    monkeypatch.setenv("MOBIUS_HOME", str(home))

    result = CliRunner().invoke(app, ["grade", "--json"], catch_exceptions=False)
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["grade"] == "gold"


def test_grade_cli_markdown_exits_nonzero_when_not_gold(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("MOBIUS_HOME", str(home))

    result = CliRunner().invoke(app, ["grade"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "# Mobius Grade" in result.stdout
    assert "bronze" in result.stdout
