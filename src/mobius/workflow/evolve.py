"""Evolution workflow execution helpers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from mobius.cli.main import ExitCode
from mobius.config import MobiusPaths
from mobius.persistence.event_store import EventStore

MAX_GENERATIONS = 30
CONVERGENCE_THRESHOLD = 0.95
QUESTION_OVERLAP_THRESHOLD = 0.70


class EvolutionSourceNotFoundError(ValueError):
    """Raised when an evolution source run cannot be found."""


@dataclass(frozen=True)
class EvolutionPaths:
    """Filesystem paths for one evolution."""

    directory: Path
    pid_file: Path
    log_file: Path
    metadata_file: Path


@dataclass(frozen=True)
class PreparedEvolution:
    """A prepared evolution ready to execute."""

    evolution_id: str
    source_run_id: str
    generations: int
    paths: EvolutionPaths


def get_evolution_paths(paths: MobiusPaths, evolution_id: str) -> EvolutionPaths:
    """Return the evolution directory paths for ``evolution_id``."""
    directory = paths.state_dir / "evolutions" / evolution_id
    return EvolutionPaths(
        directory=directory,
        pid_file=directory / "pid",
        log_file=directory / "log",
        metadata_file=directory / "metadata.json",
    )


def prepare_evolution(
    paths: MobiusPaths,
    source_run_id: str,
    *,
    generations: int,
) -> PreparedEvolution:
    """Validate the source run and create evolution metadata."""
    capped_generations = max(1, min(generations, MAX_GENERATIONS))
    with EventStore(paths.event_store) as store:
        source = store.connection.execute(
            "SELECT session_id, runtime, status FROM sessions WHERE session_id = ?",
            (source_run_id,),
        ).fetchone()
        if source is None or str(source["runtime"]) != "run":
            raise EvolutionSourceNotFoundError(f"run not found: {source_run_id}")

    evolution_id = f"evo_{uuid.uuid4().hex[:12]}"
    evolution_paths = get_evolution_paths(paths, evolution_id)
    evolution_paths.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(evolution_paths.directory, 0o700)
    evolution_paths.metadata_file.write_text(
        json.dumps(
            {"source_run_id": source_run_id, "generations": capped_generations},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(evolution_paths.metadata_file, 0o600)
    return PreparedEvolution(
        evolution_id=evolution_id,
        source_run_id=source_run_id,
        generations=capped_generations,
        paths=evolution_paths,
    )


def start_detached_worker(paths: MobiusPaths, prepared: PreparedEvolution) -> int:
    """Fork a detached evolution worker and write its PID file."""
    with EventStore(paths.event_store) as store:
        store.create_session(
            prepared.evolution_id,
            runtime="evolution",
            metadata={
                "source_run_id": prepared.source_run_id,
                "generations": prepared.generations,
            },
            status="running",
        )
    prepared.paths.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with prepared.paths.log_file.open("ab") as log_file, Path(os.devnull).open("rb") as devnull:
        process = subprocess.Popen(
            ["mobius", "_worker", "evolve", prepared.evolution_id],
            stdin=devnull,
            stdout=devnull,
            stderr=log_file,
            start_new_session=True,
        )
    _write_pid(prepared.paths.pid_file, process.pid)
    return process.pid


def run_foreground(paths: MobiusPaths, prepared: PreparedEvolution) -> int:
    """Execute evolution in the current process."""
    _write_pid(prepared.paths.pid_file, os.getpid())
    return execute_evolution(paths, prepared.evolution_id, stream_events=True)


def execute_evolution(paths: MobiusPaths, evolution_id: str, *, stream_events: bool) -> int:
    """Worker entry point for a prepared evolution."""
    evolution_paths = get_evolution_paths(paths, evolution_id)
    metadata = _read_metadata(evolution_paths)
    source_run_id = str(metadata["source_run_id"])
    metadata_generations = metadata["generations"]
    if not isinstance(metadata_generations, int):
        msg = f"evolution metadata generations must be an integer for {evolution_id}"
        raise EvolutionSourceNotFoundError(msg)
    generations = metadata_generations

    interrupted = EvolutionInterrupted(
        paths=paths,
        evolution_id=evolution_id,
        pid_file=evolution_paths.pid_file,
    )
    signal.signal(signal.SIGTERM, interrupted.handle_sigterm)
    signal.signal(signal.SIGINT, interrupted.handle_sigint)

    try:
        with EventStore(paths.event_store) as store:
            store.create_session(
                evolution_id,
                runtime="evolution",
                metadata={"source_run_id": source_run_id, "generations": generations},
                status="running",
            )
            _append_and_emit(
                store,
                evolution_id,
                "evolution.started",
                {"source_run_id": source_run_id, "max_generations": generations},
                stream_events=stream_events,
            )

            history: list[dict[str, Any]] = []
            previous_questions: list[str] = []
            terminal_reason = "max_generations"
            for generation in range(1, generations + 1):
                candidate = _candidate_for_generation(source_run_id, generation)
                similarity = calculate_similarity(history[-1], candidate) if history else 0.0
                questions = _questions_for_generation(generation)
                repetitive_feedback = bool(
                    previous_questions and detect_repetitive_feedback(previous_questions, questions)
                )
                history.append(candidate)
                oscillation = detect_period_two_oscillation(history)
                _append_and_emit(
                    store,
                    evolution_id,
                    "evolution.generation",
                    {
                        "generation": generation,
                        "candidate": candidate,
                        "similarity": similarity,
                        "converged": similarity >= CONVERGENCE_THRESHOLD,
                        "period_two_oscillation": oscillation,
                        "repetitive_feedback": repetitive_feedback,
                    },
                    stream_events=stream_events,
                )
                if similarity >= CONVERGENCE_THRESHOLD:
                    terminal_reason = "converged"
                    break
                if oscillation:
                    terminal_reason = "period_two_oscillation"
                    break
                if repetitive_feedback:
                    terminal_reason = "repetitive_feedback"
                    break
                previous_questions = questions
                time.sleep(0.2)

            _append_and_emit(
                store,
                evolution_id,
                "evolution.completed",
                {"reason": terminal_reason, "generations_run": len(history)},
                stream_events=stream_events,
            )
            store.end_session(evolution_id, status="completed")
        return int(ExitCode.OK)
    finally:
        _cleanup_pid(evolution_paths.pid_file)


class EvolutionInterrupted:
    """Signal handlers for an evolution worker."""

    def __init__(self, *, paths: MobiusPaths, evolution_id: str, pid_file: Path) -> None:
        self.paths = paths
        self.evolution_id = evolution_id
        self.pid_file = pid_file

    def handle_sigterm(self, _signum: int, _frame: object | None) -> NoReturn:
        """Handle graceful cancellation."""
        self._finish("cancelled", "evolution.cancelled")
        raise SystemExit(int(ExitCode.OK))

    def handle_sigint(self, _signum: int, _frame: object | None) -> NoReturn:
        """Handle interactive interruption."""
        self._finish("interrupted", "evolution.interrupted")
        sys.stderr.write("interrupted\n")
        raise SystemExit(int(ExitCode.INTERRUPTED))

    def _finish(self, status: str, event_type: str) -> None:
        with EventStore(self.paths.event_store) as store:
            store.append_event(self.evolution_id, event_type, {"signal": status})
            store.end_session(self.evolution_id, status=status)
        _cleanup_pid(self.pid_file)


def calculate_similarity(previous: dict[str, Any], candidate: dict[str, Any]) -> float:
    """Calculate weighted similarity: name 50%, type 30%, exact 20%."""
    score = 0.0
    if previous.get("name") == candidate.get("name"):
        score += 0.5
    if previous.get("type") == candidate.get("type"):
        score += 0.3
    if _canonical_candidate(previous) == _canonical_candidate(candidate):
        score += 0.2
    return round(score, 6)


def detect_period_two_oscillation(history: list[dict[str, Any]]) -> bool:
    """Return true when the last four candidates form A/B/A/B."""
    if len(history) < 4:
        return False
    a1, b1, a2, b2 = history[-4:]
    return (
        _canonical_candidate(a1) == _canonical_candidate(a2)
        and _canonical_candidate(b1) == _canonical_candidate(b2)
        and _canonical_candidate(a1) != _canonical_candidate(b1)
    )


def detect_repetitive_feedback(
    previous_questions: list[str],
    current_questions: list[str],
    *,
    threshold: float = QUESTION_OVERLAP_THRESHOLD,
) -> bool:
    """Return true when question overlap is at least ``threshold``."""
    if not previous_questions or not current_questions:
        return False
    previous = {_normalize_question(question) for question in previous_questions}
    current = {_normalize_question(question) for question in current_questions}
    if not previous or not current:
        return False
    overlap = len(previous & current) / min(len(previous), len(current))
    return overlap >= threshold


def _candidate_for_generation(source_run_id: str, generation: int) -> dict[str, Any]:
    name = f"{source_run_id}-candidate-{1 if generation % 2 else 2}"
    return {
        "name": name,
        "type": "acceptance-criteria",
        "payload": {"source_run_id": source_run_id, "variant": generation % 2},
    }


def _questions_for_generation(generation: int) -> list[str]:
    if generation >= 3:
        return ["What should change?", "Which acceptance criterion failed?"]
    return [f"What should change in generation {generation}?", "Which acceptance criterion failed?"]


def _append_and_emit(
    store: EventStore,
    evolution_id: str,
    event_type: str,
    payload: dict[str, object],
    *,
    stream_events: bool,
) -> None:
    event = store.append_event(evolution_id, event_type, payload)
    if stream_events:
        sys.stderr.write(f"{event.created_at} {event.type} {event.payload}\n")
        sys.stderr.flush()


def _read_metadata(evolution_paths: EvolutionPaths) -> dict[str, object]:
    try:
        metadata = json.loads(evolution_paths.metadata_file.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"evolution metadata not found for {evolution_paths.directory.name}: {exc}"
        raise EvolutionSourceNotFoundError(msg) from exc
    if not isinstance(metadata.get("source_run_id"), str) or not metadata.get("source_run_id"):
        msg = f"evolution metadata missing source_run_id for {evolution_paths.directory.name}"
        raise EvolutionSourceNotFoundError(msg)
    if not isinstance(metadata.get("generations"), int):
        msg = f"evolution metadata missing generations for {evolution_paths.directory.name}"
        raise EvolutionSourceNotFoundError(msg)
    return dict(metadata)


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(f"{pid}\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(path)
    os.chmod(path, 0o600)


def _cleanup_pid(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def _canonical_candidate(candidate: dict[str, Any]) -> str:
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"))


def _normalize_question(question: str) -> str:
    return " ".join(question.strip().lower().rstrip("?").split())
