from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mobius.v3a.phase_router.router import PhaseRouter


class MemoryEventSink:
    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: object,
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> None:
        return None


def test_phase_router_creates_only_one_rich_live_instance_per_router() -> None:
    calls: list[object] = []

    def record_init(self: object, *_args: object, **_kwargs: object) -> None:
        calls.append(self)

    router = PhaseRouter(run_id="build-test", event_sink=MemoryEventSink())

    with patch("rich.live.Live.__init__", side_effect=record_init, autospec=True):
        router._create_live()
        with pytest.raises(RuntimeError, match="more than one Rich.Live"):
            router._create_live()

    assert len(calls) == 1


def test_build_process_lock_rejects_concurrent_invocation(tmp_path: Path) -> None:
    from mobius.v3a.phase_router.router import BuildLockError, build_process_lock

    first_lock = build_process_lock(tmp_path)
    first_lock.__enter__()
    try:
        with pytest.raises(BuildLockError), build_process_lock(tmp_path):
            pass
    finally:
        first_lock.__exit__(None, None, None)
