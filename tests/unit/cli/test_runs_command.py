from __future__ import annotations

import json
from pathlib import Path

import pytest

from mobius.cli.commands import runs as runs_command
from mobius.cli.main import CliContext
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore


class _Event:
    def __init__(self, event_type: str, payload: str = "{}") -> None:
        self.type = event_type
        self.payload = payload


def test_runs_ls_rich_table_shows_enriched_columns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_a", runtime="run", status="completed")
        store.append_event("run_a", "run.started", {"title": "Ship richer run lists"})
        store.append_event("run_a", "run.completed", {"success_criteria_count": 3})
        store.end_session("run_a", status="completed")

    runs_command.ls(ctx)

    captured = capsys.readouterr().out
    assert "ID" in captured
    assert "Title" in captured
    assert "Status" in captured
    assert "Started" in captured
    assert "Duration" in captured
    assert "Criteria" in captured
    assert "run_a" in captured
    assert "Ship richer run lists" in captured
    assert "3/0/0" in captured


def test_runs_ls_json_contains_same_enriched_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_b", runtime="run", status="running")
        store.append_event("run_b", "run.started", {"goal": "Track criteria counts"})
        store.append_event("run_b", "run.progress", {"success_criteria_count": 2})

    runs_command.ls(ctx, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    row = payload["runs"][0]
    assert row["run_id"] == "run_b"
    assert row["title"] == "Track criteria counts"
    assert row["status"] == "running"
    assert row["started"]
    assert row["duration"]
    assert row["criteria"] == "0/0/2"
    assert row["criteria_passed"] == 0
    assert row["criteria_failed"] == 0
    assert row["criteria_unverified"] == 2


def test_runs_ls_prefers_latest_qa_criteria_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_c", runtime="run", status="failed")
        store.append_event("run_c", "run.started", {"title": "Use QA verdicts"})
        store.append_event("run_c", "run.completed", {"success_criteria_count": 5})
        store.append_event(
            "run_c",
            "qa.completed",
            {"summary": {"passed": 1, "failed": 2, "unverified": 2}},
        )
        store.end_session("run_c", status="failed")

    runs_command.ls(ctx, json_output=True)

    row = json.loads(capsys.readouterr().out)["runs"][0]
    assert row["criteria"] == "1/2/2"


def test_runs_ls_filters_by_runtime_and_bounds_limit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_regular", runtime="run", status="completed")
        store.append_event("run_regular", "run.started", {"title": "Regular"})
        store.create_session("run_evolve", runtime="evolution", status="running")
        store.append_event("run_evolve", "run.started", {"title": "Evolution"})

    runs_command.ls(ctx, limit=0, runtime="evolution", json_output=True)

    rows = json.loads(capsys.readouterr().out)["runs"]
    assert [row["run_id"] for row in rows] == ["run_evolve"]


def test_runs_helpers_cover_fallbacks_and_duration_formats() -> None:
    assert runs_command._title_from_events([_Event("run.started", '{"goal":"Fallback goal"}')]) == (
        "Fallback goal"
    )
    assert runs_command._title_from_events([_Event("run.started", "{}")]) == "(untitled)"

    failed_counts = runs_command._criteria_counts(
        "failed",
        [_Event("run.completed", '{"success_criteria_count":2}')],
    )
    assert failed_counts == (
        0,
        2,
        0,
    )
    assert runs_command._criteria_counts("running", [_Event("run.started", "{}")]) == (0, 0, 0)
    incomplete_qa_counts = runs_command._latest_qa_counts(
        [_Event("qa.completed", '{"passed":1,"failed":0}')],
    )
    assert incomplete_qa_counts is None
    assert runs_command._payload_data(_Event("broken", "{")) == {}
    assert runs_command._payload_data(_Event("list", "[]")) == {}
    event_with_non_str_payload = _Event("non-str")
    event_with_non_str_payload.payload = object()  # type: ignore[assignment]
    assert runs_command._payload_data(event_with_non_str_payload) == {}
    assert runs_command._int_from_payload({"value": "1"}, "value") is None

    assert runs_command._format_duration("bad", "also-bad") == "unknown"
    assert runs_command._format_duration("2026-04-28T00:00:00Z", "2026-04-28T00:00:05Z") == "5s"
    assert runs_command._format_duration("2026-04-28T00:00:00Z", "2026-04-28T00:02:05Z") == "2m 5s"
    assert runs_command._format_duration("2026-04-28T00:00:00Z", "2026-04-28T02:05:00Z") == "2h 5m"
    assert runs_command._colored_status("mystery") == "[white]mystery[/white]"
