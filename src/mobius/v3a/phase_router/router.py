"""Four-phase state machine and renderer for ``mobius build``."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mobius.v3a.phase_router.transitions import (
    PHASE_BY_KEY,
    PHASES,
    PhaseDefinition,
    narrative_line,
    status_line,
)


class EventSink(Protocol):
    """Event-store surface required by the phase router."""

    def append_event(
        self,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        sequence: int | None = None,
        event_id: str | None = None,
    ) -> Any:
        """Append one event to the backing store."""


@dataclass(frozen=True)
class PhaseResult:
    """Result returned by an executable build phase."""

    summary: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    turn: int = 0
    ambiguity_score: float = 0.0
    converged_proposed: bool = False


@dataclass(frozen=True)
class AgentPhasePayload:
    """JSON payload emitted for coding-agent orchestration."""

    phase_done: str
    next_phase: str | None
    next_command: str
    converged_proposed: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return {
            "phase_done": self.phase_done,
            "next_phase": self.next_phase,
            "next_command": self.next_command,
            "converged_proposed": self.converged_proposed,
            **dict(self.details),
        }


PhaseHandler = Callable[[PhaseDefinition], PhaseResult]


@dataclass
class PhaseRouter:
    """Own the v3a build phase transitions and all live rendering."""

    run_id: str
    event_sink: EventSink
    mode: str = "interactive"
    wizard_countdown_seconds: int = 5
    _live_created: bool = False

    def run(
        self,
        handlers: Mapping[str, PhaseHandler],
        *,
        start_phase_key: str = "interview",
    ) -> list[AgentPhasePayload]:
        """Run all four phases and return the agent payloads emitted."""
        agent_payloads: list[AgentPhasePayload] = []
        start_phase = PHASE_BY_KEY[start_phase_key]
        with self._renderer():
            for phase in PHASES[start_phase.index - 1 :]:
                self._emit("phase.entered", {"phase": phase.key, "phase_index": phase.index})
                result = handlers[phase.key](phase)
                next_phase = PHASE_BY_KEY.get(phase.next_key or "")
                completed_payload = {
                    "phase": phase.key,
                    "phase_index": phase.index,
                    "summary": result.summary,
                    **dict(result.payload),
                }
                self._emit("phase.completed", completed_payload)
                proposed_next_payload = {
                    "phase_done": phase.key,
                    "next_phase": phase.next_key,
                    "next_command": phase.next_command,
                }
                self._emit("phase.proposed_next", proposed_next_payload)
                agent_payload = AgentPhasePayload(
                    phase_done=phase.key,
                    next_phase=phase.next_key,
                    next_command=phase.next_command,
                    converged_proposed=result.converged_proposed,
                    details=result.payload,
                )
                agent_payloads.append(agent_payload)
                self._render_phase_complete(phase, result, next_phase, agent_payload)
        return agent_payloads

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.event_sink.append_event(self.run_id, event_type, payload)

    @contextmanager
    def _renderer(self) -> Iterator[None]:
        if self.mode == "agent":
            yield
            return
        live = self._create_live()
        with live:
            yield

    def _create_live(self) -> Any:
        """Create the single Rich.Live instance for this process."""
        if self._live_created:
            msg = "PhaseRouter attempted to create more than one Rich.Live instance"
            raise RuntimeError(msg)
        self._live_created = True
        from rich.live import Live

        return Live("", refresh_per_second=4, transient=True)

    def _render_phase_complete(
        self,
        phase: PhaseDefinition,
        result: PhaseResult,
        next_phase: PhaseDefinition | None,
        agent_payload: AgentPhasePayload,
    ) -> None:
        if self.mode == "agent":
            sys.stdout.write(
                json.dumps(agent_payload.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
            )
            return
        rendered_status = status_line(
            phase,
            turn=result.turn,
            ambiguity_score=result.ambiguity_score,
        )
        sys.stdout.write(rendered_status)
        sys.stdout.write("\n")
        sys.stdout.write(narrative_line(phase, result.summary, next_phase=next_phase))
        sys.stdout.write("\n")
        handoff_display = result.payload.get("handoff_display")
        if phase.key == "scoring" and isinstance(handoff_display, str):
            sys.stdout.write(handoff_display)
            sys.stdout.write("\n")
        if self.mode == "wizard" and next_phase is not None:
            self._render_wizard_countdown(next_phase)

    def _render_wizard_countdown(self, next_phase: PhaseDefinition) -> None:
        for remaining in range(self.wizard_countdown_seconds, 0, -1):
            sys.stdout.write(
                f"Auto-proceeding to Phase {next_phase.index}/{len(PHASES)} "
                f"in {remaining}s...\n"
            )


@contextmanager
def build_process_lock(mobius_home: Path) -> Iterator[None]:
    """Acquire the ``mobius build`` process lock under ``$MOBIUS_HOME``."""
    import fcntl

    lock_dir = mobius_home.expanduser()
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "build.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            msg = f"another mobius build invocation is already running: {lock_path}"
            raise BuildLockError(msg) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class BuildLockError(RuntimeError):
    """Raised when the build process lock is already held."""


def wizard_countdown_from_env(default: int = 5) -> int:
    """Return the configured wizard countdown duration."""
    raw_value = os.environ.get("MOBIUS_V3A_WIZARD_COUNTDOWN")
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return max(0, parsed)
