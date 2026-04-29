from __future__ import annotations

from io import StringIO

from mobius.persistence.event_store import EventStore
from mobius.v3a.phase_router.tour import (
    TOUR_EVENT_TYPE,
    has_prior_project_events,
    maybe_run_first_run_tour,
)


def test_first_run_tour_appends_completion_event_on_empty_project_store(tmp_path) -> None:
    output = StringIO()
    answers = iter(["\n", "\n", "\n"])

    with EventStore(tmp_path / ".mobius" / "build" / "events.db") as store:
        assert has_prior_project_events(store) is False

        result = maybe_run_first_run_tour(
            store,
            run_id="build-tour",
            input_fn=lambda: next(answers),
            output=output,
        )
        events = store.read_events("build-tour")

    assert result.shown is True
    assert result.completed is True
    assert result.skipped is False
    assert result.screens_seen == 3
    assert output.getvalue().count("[first run detected — 60s tour]") == 3
    assert [event.type for event in events] == [TOUR_EVENT_TYPE]
    assert events[0].payload_data["scope"] == ".mobius/build/events.db"


def test_first_run_tour_skips_when_project_store_has_prior_events(tmp_path) -> None:
    output = StringIO()

    with EventStore(tmp_path / ".mobius" / "build" / "events.db") as store:
        store.append_event("prior-build", "phase.entered", {"phase": "interview"})

        result = maybe_run_first_run_tour(
            store,
            run_id="build-tour",
            input_fn=lambda: "\n",
            output=output,
        )

    assert result.shown is False
    assert result.completed is False
    assert result.skipped is False
    assert output.getvalue() == ""


def test_skip_tour_flag_bypasses_without_appending_event(tmp_path) -> None:
    output = StringIO()

    with EventStore(tmp_path / ".mobius" / "build" / "events.db") as store:
        result = maybe_run_first_run_tour(
            store,
            run_id="build-tour",
            skip_tour=True,
            input_fn=lambda: "\n",
            output=output,
        )
        events = store.read_events("build-tour")

    assert result.shown is False
    assert result.skipped is True
    assert output.getvalue() == ""
    assert events == []


def test_q_records_skipped_tour_completion(tmp_path) -> None:
    output = StringIO()

    with EventStore(tmp_path / ".mobius" / "build" / "events.db") as store:
        result = maybe_run_first_run_tour(
            store,
            run_id="build-tour",
            input_fn=lambda: "q\n",
            output=output,
        )
        events = store.read_events("build-tour")

    assert result.shown is True
    assert result.completed is False
    assert result.skipped is True
    assert result.screens_seen == 1
    assert events[0].type == TOUR_EVENT_TYPE
    assert events[0].payload_data["skipped"] is True
