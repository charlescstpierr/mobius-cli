"""Branch-coverage tests for the evolve workflow logic functions."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from mobius.cli.main import ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.evolve import (
    EvolutionInterrupted,
    EvolutionSourceNotFoundError,
    calculate_similarity,
    detect_period_two_oscillation,
    detect_repetitive_feedback,
    execute_evolution,
    get_evolution_paths,
    prepare_evolution,
)


def test_calculate_similarity_identical_pair_is_one() -> None:
    candidate = {"name": "X", "type": "Y", "payload": {"a": 1}}
    assert calculate_similarity(candidate, candidate) == 1.0


def test_calculate_similarity_different_name_drops_to_partial() -> None:
    a = {"name": "A", "type": "Y", "payload": {}}
    b = {"name": "B", "type": "Y", "payload": {}}
    score = calculate_similarity(a, b)
    assert 0.0 < score < 1.0


def test_calculate_similarity_zero_when_all_differ() -> None:
    a = {"name": "A", "type": "X", "payload": {"a": 1}}
    b = {"name": "B", "type": "Y", "payload": {"a": 2}}
    assert calculate_similarity(a, b) == 0.0


def test_detect_period_two_oscillation_short_history_is_false() -> None:
    assert detect_period_two_oscillation([]) is False
    assert detect_period_two_oscillation([{"name": "A"}]) is False


def test_detect_period_two_oscillation_finds_abab() -> None:
    history = [
        {"name": "A", "type": "ac", "payload": {}},
        {"name": "B", "type": "ac", "payload": {}},
        {"name": "A", "type": "ac", "payload": {}},
        {"name": "B", "type": "ac", "payload": {}},
    ]
    assert detect_period_two_oscillation(history) is True


def test_detect_period_two_oscillation_when_a_eq_b_is_false() -> None:
    """A and B identical means it's not actually oscillating between two states."""
    same = {"name": "A", "type": "ac", "payload": {}}
    history = [same, same, same, same]
    assert detect_period_two_oscillation(history) is False


def test_detect_repetitive_feedback_overlap_threshold() -> None:
    prev = ["What changed?", "Which failed?"]
    curr = ["What changed?", "Which failed?"]
    assert detect_repetitive_feedback(prev, curr) is True


def test_detect_repetitive_feedback_no_overlap() -> None:
    prev = ["A?", "B?"]
    curr = ["C?", "D?"]
    assert detect_repetitive_feedback(prev, curr) is False


def test_detect_repetitive_feedback_empty_inputs_are_false() -> None:
    assert detect_repetitive_feedback([], ["x"]) is False
    assert detect_repetitive_feedback(["x"], []) is False


def test_prepare_evolution_unknown_source_raises(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    with pytest.raises(EvolutionSourceNotFoundError):
        prepare_evolution(paths, "run_does_not_exist", generations=2)


def test_prepare_evolution_caps_generations(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_src", runtime="run", metadata={}, status="completed")
    prepared = prepare_evolution(paths, "run_src", generations=999)
    # The hard cap is 30 per the CLI option; prepare_evolution clamps higher.
    assert prepared.generations <= 30


def test_execute_evolution_missing_metadata_raises(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    evo = get_evolution_paths(paths, "evo_no_meta")
    evo.directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(EvolutionSourceNotFoundError, match="metadata"):
        execute_evolution(paths, "evo_no_meta", stream_events=False)


def test_execute_evolution_metadata_missing_source_raises(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    evo = get_evolution_paths(paths, "evo_no_src")
    evo.directory.mkdir(parents=True, exist_ok=True)
    evo.metadata_file.write_text(json.dumps({"generations": 2}), encoding="utf-8")
    with pytest.raises(EvolutionSourceNotFoundError, match="source_run_id"):
        execute_evolution(paths, "evo_no_src", stream_events=False)


def test_execute_evolution_metadata_missing_generations_raises(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    evo = get_evolution_paths(paths, "evo_no_gen")
    evo.directory.mkdir(parents=True, exist_ok=True)
    evo.metadata_file.write_text(json.dumps({"source_run_id": "run_src"}), encoding="utf-8")
    with pytest.raises(EvolutionSourceNotFoundError, match="generations"):
        execute_evolution(paths, "evo_no_gen", stream_events=False)


def test_execute_evolution_completes_with_max_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run_src", runtime="run", metadata={}, status="completed")
    evo = get_evolution_paths(paths, "evo_full")
    evo.directory.mkdir(parents=True, exist_ok=True)
    evo.metadata_file.write_text(
        json.dumps({"source_run_id": "run_src", "generations": 1}),
        encoding="utf-8",
    )
    # Avoid sleeping during the test.
    import mobius.workflow.evolve as evolve_mod

    monkeypatch.setattr(evolve_mod.time, "sleep", lambda _seconds: None)
    code = execute_evolution(paths, "evo_full", stream_events=False)
    assert code == int(ExitCode.OK)


def test_evolution_interrupted_sigterm_marks_cancelled(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("evo_z", runtime="evolution", metadata={}, status="running")
    evo = get_evolution_paths(paths, "evo_z")
    evo.directory.mkdir(parents=True, exist_ok=True)
    evo.pid_file.write_text("1\n", encoding="utf-8")

    interrupted = EvolutionInterrupted(paths=paths, evolution_id="evo_z", pid_file=evo.pid_file)
    with pytest.raises(SystemExit) as exc:
        interrupted.handle_sigterm(signal.SIGTERM, None)
    assert exc.value.code == int(ExitCode.OK)


def test_evolution_interrupted_sigint_marks_interrupted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = get_paths(tmp_path / "h")
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("evo_y", runtime="evolution", metadata={}, status="running")
    evo = get_evolution_paths(paths, "evo_y")
    evo.directory.mkdir(parents=True, exist_ok=True)
    evo.pid_file.write_text("1\n", encoding="utf-8")

    interrupted = EvolutionInterrupted(paths=paths, evolution_id="evo_y", pid_file=evo.pid_file)
    with pytest.raises(SystemExit) as exc:
        interrupted.handle_sigint(signal.SIGINT, None)
    assert exc.value.code == int(ExitCode.INTERRUPTED)
    assert "interrupted" in capsys.readouterr().err
