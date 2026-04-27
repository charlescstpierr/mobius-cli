from pathlib import Path

from mobius.persistence.event_store import EventStore
from mobius.workflow.qa import evaluate_run_qa


def write_spec(path: Path, *, success_criteria: bool = True) -> None:
    success_block = "  - QA returns a passing verdict" if success_criteria else ""
    path.write_text(
        f"""
project_type: greenfield
goal: Judge a run without using an LLM.
constraints:
  - Use deterministic offline heuristics
success_criteria:
{success_block}
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
    assert report.summary.total == len(report.results)
    assert report.summary.failed == 0
    assert all(result.passed for result in report.results)


def test_evaluate_run_qa_fails_non_completed_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_spec(spec)
    store_path = tmp_path / "events.db"
    create_failed_run(store_path, "run_bad", spec)

    report = evaluate_run_qa(store_path, "run_bad")

    assert report is not None
    assert report.summary.total == len(report.results)
    assert report.summary.failed > 0
    failed_ids = {result.id for result in report.results if not result.passed}
    assert "run_completed_successfully" in failed_ids
    assert "no_failure_events" in failed_ids


def test_evaluate_run_qa_returns_none_for_unknown_run(tmp_path: Path) -> None:
    report = evaluate_run_qa(tmp_path / "events.db", "run_missing")

    assert report is None
