"""Hypothesis property-based tests for the event store."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mobius.persistence.event_store import EventStore

# Bound the strategies tightly so the test stays fast.
_event_types = st.sampled_from(
    [
        "seed.created",
        "run.started",
        "run.progress",
        "run.completed",
        "evolve.iteration",
        "qa.verdict",
    ]
)
_payload_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-10_000, max_value=10_000),
        st.text(max_size=20),
    ),
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(min_size=1, max_size=8), children, max_size=3)
    ),
    max_leaves=8,
)
_payloads = st.dictionaries(
    st.text(min_size=1, max_size=8),
    _payload_values,
    max_size=4,
)
_events_for_one_aggregate = st.lists(
    st.tuples(_event_types, _payloads),
    min_size=1,
    max_size=8,
)


@given(events=_events_for_one_aggregate)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_replay_hash_and_status_are_deterministic_for_any_valid_sequence(
    events: list[tuple[str, dict[str, object]]],
) -> None:
    """For any valid event sequence, replay() and integrity_check are deterministic."""
    with tempfile.TemporaryDirectory() as one_dir, tempfile.TemporaryDirectory() as two_dir:
        db_one = Path(one_dir) / "events.db"
        db_two = Path(two_dir) / "events.db"

        with EventStore(db_one) as store:
            for event_type, payload in events:
                store.append_event("agg-prop", event_type, payload)
            first_hash = store.replay_hash("agg-prop")
            first_types = [event.type for event in store.read_events("agg-prop")]
            first_integrity = store.integrity_check()

        with EventStore(db_two) as store:
            for event_type, payload in events:
                store.append_event("agg-prop", event_type, payload)
            second_hash = store.replay_hash("agg-prop")
            second_types = [event.type for event in store.read_events("agg-prop")]
            second_integrity = store.integrity_check()

        # Determinism: same input sequence → same replay hash and event order.
        assert first_hash == second_hash
        assert first_types == second_types == [event_type for event_type, _ in events]
        assert first_integrity == second_integrity == "ok"

        # Reopening the same DB must still produce the same replay hash.
        with EventStore(db_one) as store:
            reopened_hash = store.replay_hash("agg-prop")
        assert reopened_hash == first_hash
