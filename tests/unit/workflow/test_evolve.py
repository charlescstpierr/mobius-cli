import json
import os
from pathlib import Path

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.evolve import (
    calculate_similarity,
    detect_period_two_oscillation,
    detect_repetitive_feedback,
    get_evolution_paths,
    prepare_evolution,
)


def create_completed_run(home: Path, run_id: str = "run_source") -> None:
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "Build a CLI"})
        store.end_session(run_id, status="completed")


def test_prepare_evolution_caps_generations_and_writes_metadata(tmp_path: Path) -> None:
    create_completed_run(tmp_path / "home")
    paths = get_paths(tmp_path / "home")

    prepared = prepare_evolution(paths, "run_source", generations=99)

    assert prepared.evolution_id.startswith("evo_")
    assert prepared.source_run_id == "run_source"
    assert prepared.generations == 30
    assert prepared.paths == get_evolution_paths(paths, prepared.evolution_id)
    metadata = json.loads(prepared.paths.metadata_file.read_text(encoding="utf-8"))
    assert metadata["source_run_id"] == "run_source"
    assert metadata["generations"] == 30
    assert oct(os.stat(prepared.paths.metadata_file).st_mode & 0o777) == "0o600"


def test_similarity_weights_name_type_and_exact_components() -> None:
    previous = {"name": "alpha", "type": "task", "payload": {"done": True}}

    assert calculate_similarity(previous, previous) == 1.0
    assert calculate_similarity(previous, {"name": "alpha", "type": "task"}) == 0.8
    assert calculate_similarity(previous, {"name": "alpha", "type": "other"}) == 0.5
    assert calculate_similarity(previous, {"name": "beta", "type": "task"}) == 0.3


def test_period_two_oscillation_detection() -> None:
    assert detect_period_two_oscillation(
        [
            {"name": "a", "type": "task"},
            {"name": "b", "type": "task"},
            {"name": "a", "type": "task"},
            {"name": "b", "type": "task"},
        ]
    )
    assert not detect_period_two_oscillation(
        [
            {"name": "a", "type": "task"},
            {"name": "b", "type": "task"},
            {"name": "c", "type": "task"},
        ]
    )


def test_repetitive_feedback_detects_question_overlap() -> None:
    previous = ["What should Mobius do?", "Which runtime should it use?"]
    current = ["What should Mobius do?", "Which runtime should it use?", "Any constraints?"]

    assert detect_repetitive_feedback(previous, current, threshold=0.70)
    assert not detect_repetitive_feedback(previous, ["Completely different?"], threshold=0.70)
