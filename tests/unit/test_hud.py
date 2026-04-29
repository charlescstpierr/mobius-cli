import json
import time
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.persistence.event_store import EventStore
from mobius.workflow.hud import build_hud_summary, load_hud


def test_hud_outputs_projection_backed_summary(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    home = tmp_path / "home"
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event(
            "seed-1",
            "seed.completed",
            {
                "goal": "Ship the HUD.",
                "owner": "alice",
                "success_criteria": ["C1 - First passes.", "C2 - Needs verification."],
                "verification_commands": [
                    {"command": "python -m pytest tests/c1.py", "criterion_ref": "C1"},
                    {"command": "python -m pytest tests/c2.py", "criterion_ref": "C2"},
                ],
            },
        )
        store.append_event(
            "seed-1",
            "spec.grade_assigned",
            {"grade": "silver", "criteria_met": 7, "criteria_total": 7},
        )
        store.append_event("run-hud-1", "run.started", {"goal": "Ship", "title": "Ship HUD"})
        for index in range(100):
            store.append_event("run-hud-1", "run.progress", {"step": index})
        store.append_event(
            "run-hud-1",
            "qa.proof_collected",
            {
                "command": "python -m pytest tests/c1.py",
                "criterion_ref": "C1",
                "exit_code": 0,
                "timed_out": False,
            },
        )

    monkeypatch.setenv("MOBIUS_HOME", str(home))
    started = time.perf_counter()
    result = CliRunner().invoke(app, ["hud"], catch_exceptions=False)
    duration_ms = (time.perf_counter() - started) * 1000

    assert result.exit_code == 0
    assert duration_ms < 200
    assert "## Current Spec" in result.stdout
    assert "Ship the HUD." in result.stdout
    assert "alice" in result.stdout
    assert "silver" in result.stdout
    assert "C1 - First passes." in result.stdout
    assert "C2 - Needs verification." in result.stdout
    assert "python -m pytest tests/c2.py" in result.stdout
    assert "- Collected: 1" in result.stdout
    assert "- Last QA:" in result.stdout


def test_hud_json_contains_criteria_grade_and_last_qa(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    home = tmp_path / "home"
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event(
            "seed-1",
            "seed.completed",
            {
                "goal": "Show JSON.",
                "owner": ["alice", "bob"],
                "success_criteria": ["C1"],
                "verification_commands": [
                    {"command": "true", "criterion_ref": "C1"},
                ],
            },
        )
        store.append_event("run-json", "run.started", {"goal": "Show JSON", "title": "Show JSON"})
        store.append_event(
            "run-json",
            "qa.proof_collected",
            {"command": "true", "criterion_ref": "C1", "exit_code": 0, "timed_out": False},
        )
        store.append_event("run-json", "spec.grade_assigned", {"grade": "silver"})

    monkeypatch.setenv("MOBIUS_HOME", str(home))
    result = CliRunner().invoke(app, ["hud", "--json"], catch_exceptions=False)
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["spec"]["goal"] == "Show JSON."
    assert payload["spec"]["owner"] == "alice, bob"
    assert payload["spec"]["grade"] == "silver"
    assert payload["criteria"][0]["verdict"] == "pass"
    assert payload["proofs_collected"] == 1
    assert payload["last_qa_timestamp"].endswith("Z")


def test_load_hud_reads_projection_snapshot_without_event_replay(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    queries: list[str] = []

    class FakeConnection:
        def execute(self, sql: str, _params: object = ()) -> object:
            queries.append(sql)
            assert "FROM events" not in sql
            return object()

    class FakeStore:
        connection = FakeConnection()

        def __init__(self, _path: Path, *, read_only: bool) -> None:
            assert read_only is True

        def __enter__(self) -> "FakeStore":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_snapshot(connection: FakeConnection) -> dict[str, Any]:
        connection.execute("SELECT snapshot FROM aggregates WHERE aggregate_id = ?")
        return {"current_spec": {"goal": "Cached only"}}

    db_path = tmp_path / "events.db"
    db_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("mobius.workflow.hud.EventStore", FakeStore)
    monkeypatch.setattr("mobius.workflow.hud.load_projection_snapshot", fake_snapshot)

    result = load_hud(db_path)

    assert result.summary.spec.goal == "Cached only"
    assert len(queries) == 1


def test_load_hud_handles_missing_event_store(tmp_path: Path) -> None:
    result = load_hud(tmp_path / "missing.db")

    assert result.projection_snapshot == {}
    assert result.summary.spec.goal == "(unknown)"
    assert result.summary.latest_run.duration == "unknown"


def test_build_hud_summary_covers_fallbacks_and_duration_branches() -> None:
    summary = build_hud_summary(
        {
            "current_spec": {"goal": "", "owner": []},
            "last_grade": {},
            "latest_run": {
                "id": "run-hours",
                "title": "Hours",
                "status": "completed",
                "started_at": "2026-04-28T00:00:00.000000Z",
                "ended_at": "2026-04-28T01:02:00.000000Z",
            },
            "criteria": ["bad", {"id": "", "label": "", "verdict": "", "commands": "bad"}],
            "proofs_collected": "3",
        }
    )

    assert summary.spec.goal == "(unknown)"
    assert summary.spec.owner == "(none)"
    assert summary.spec.grade == "ungraded"
    assert summary.latest_run.duration == "1h 2m"
    assert summary.criteria[0].id == "C2"
    assert summary.criteria[0].label == "Criterion 2"
    assert summary.criteria[0].verdict == "unverified"
    assert summary.criteria[0].commands == []
    assert summary.proofs_collected == 3


def test_build_hud_summary_uses_criteria_summary_fallback_and_running_duration() -> None:
    summary = build_hud_summary(
        {
            "criteria_summary": {"by_criterion": {"C2": "FAIL", "C1": "UNVERIFIED"}},
            "latest_run": {
                "id": "run-live",
                "title": "Live",
                "status": "running",
                "started_at": "2026-04-28T00:00:00.000000Z",
            },
            "proofs_collected": "not-a-number",
        }
    )

    assert summary.latest_run.duration == "running"
    assert [criterion.id for criterion in summary.criteria] == ["C1", "C2"]
    assert summary.criteria[0].verdict == "unverified"
    assert summary.proofs_collected == 0


def test_build_hud_summary_duration_short_and_invalid_values() -> None:
    short = build_hud_summary(
        {
            "latest_run": {
                "started_at": "2026-04-28T00:00:00.000000Z",
                "ended_at": "2026-04-28T00:00:42.000000Z",
            }
        }
    )
    subsecond = build_hud_summary(
        {
            "latest_run": {
                "started_at": "2026-04-28T00:00:00.000000Z",
                "ended_at": "2026-04-28T00:00:00.100000Z",
            }
        }
    )
    invalid = build_hud_summary({"latest_run": {"started_at": "bad", "ended_at": "bad"}})

    assert short.latest_run.duration == "42s"
    assert subsecond.latest_run.duration == "0.1s"
    assert invalid.latest_run.duration == "unknown"
