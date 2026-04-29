"""First-run guided tour for ``mobius build``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TextIO

TOUR_EVENT_TYPE = "human.tour_completed"

TOUR_SCREENS: tuple[str, ...] = (
    (
        "[first run detected — 60s tour]\n"
        "Screen 1/3 — The 4-phase path\n"
        "Mobius build guides one project through Interview, Seed, Maturity, "
        "and Scoring + Delivery."
    ),
    (
        "[first run detected — 60s tour]\n"
        "Screen 2/3 — Phase 1 and 2\n"
        "Interview clarifies intent with Socrate, Avocat, and Architecte. "
        "Seed then writes a v2-compatible spec.yaml."
    ),
    (
        "[first run detected — 60s tour]\n"
        "Screen 3/3 — Phase 3 and 4\n"
        "Maturity checks whether the spec is ready. Scoring + Delivery creates "
        "score.json and the handoff prompt."
    ),
)


class TourEventStore(Protocol):
    """Event-store surface needed by the first-run tour."""

    @property
    def connection(self) -> Any:
        """Expose the underlying SQLite connection."""

    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> Any:
        """Append one event."""


@dataclass(frozen=True)
class TourResult:
    """Outcome of a first-run tour check."""

    shown: bool
    completed: bool
    skipped: bool
    screens_seen: int = 0


def has_prior_project_events(store: TourEventStore) -> bool:
    """Return true when the per-project build EventStore has non-bootstrap events."""
    row = store.connection.execute(
        """
        SELECT 1
        FROM events
        WHERE type != 'mobius.bootstrap'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def maybe_run_first_run_tour(
    store: TourEventStore,
    *,
    run_id: str,
    skip_tour: bool = False,
    input_fn: Callable[[], str] | None = None,
    output: TextIO | None = None,
) -> TourResult:
    """Display the first-run tour if this project's build EventStore is empty."""
    if skip_tour or has_prior_project_events(store):
        return TourResult(shown=False, completed=False, skipped=skip_tour)

    if input_fn is None or output is None:
        import sys

        input_fn = input_fn or _stdin_line_or_enter
        output = output or sys.stdout

    screens_seen = 0
    skipped = False
    for screen_index, screen in enumerate(TOUR_SCREENS, start=1):
        screens_seen = screen_index
        output.write(screen)
        output.write("\nPress Enter to continue, or q to skip the tour.\n> ")
        output.flush()
        response = input_fn().strip().lower()
        output.write("\n")
        if response == "q":
            skipped = True
            break

    store.append_event(
        run_id,
        TOUR_EVENT_TYPE,
        {
            "completed": not skipped,
            "skipped": skipped,
            "screens_seen": screens_seen,
            "total_screens": len(TOUR_SCREENS),
            "scope": ".mobius/build/events.db",
        },
    )
    return TourResult(
        shown=True,
        completed=not skipped,
        skipped=skipped,
        screens_seen=screens_seen,
    )


def _stdin_line_or_enter() -> str:
    """Read one line without blocking automated non-TTY invocations."""
    import io
    import sys

    if sys.stdin.isatty():
        return sys.stdin.readline()

    import select

    try:
        readable, _, _ = select.select([sys.stdin], [], [], 0)
    except (io.UnsupportedOperation, OSError):
        return "\n"
    if not readable:
        return "\n"
    return sys.stdin.readline()
