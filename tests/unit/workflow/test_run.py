from pathlib import Path

import pytest

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow import run as run_workflow
from mobius.workflow.run import get_run_paths, prepare_run
from mobius.workflow.seed import SeedSpecValidationError


def write_valid_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Execute a run from a validated spec.
constraints:
  - Persist events atomically
success_criteria:
  - Worker writes progress
""".strip(),
        encoding="utf-8",
    )


def test_prepare_run_validates_spec_and_writes_metadata(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    paths = get_paths(tmp_path / "home")

    prepared = prepare_run(paths, spec)

    assert prepared.run_id.startswith("run_execute-a-run-from-a-validated-spec_")
    assert prepared.spec.goal == "Execute a run from a validated spec."
    assert prepared.paths.metadata_file.exists()
    assert str(spec.resolve()) in prepared.paths.metadata_file.read_text(encoding="utf-8")
    assert get_run_paths(paths, prepared.run_id).directory == prepared.paths.directory


def test_prepare_run_rejects_invalid_spec(tmp_path: Path) -> None:
    spec = tmp_path / "invalid.yaml"
    spec.write_text("project_type: greenfield\ngoal:\nconstraints:\nsuccess_criteria:\n")

    with pytest.raises(SeedSpecValidationError):
        prepare_run(get_paths(tmp_path / "home"), spec)


def test_run_started_payload_includes_goal_derived_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: This is a deliberately long goal that should become a concise display title for the run.
constraints:
  - Persist events atomically
success_criteria:
  - Worker writes progress
""".strip(),
        encoding="utf-8",
    )
    paths = get_paths(tmp_path / "home")
    prepared = prepare_run(paths, spec)
    monkeypatch.setattr(run_workflow, "_sleep_with_heartbeats", lambda *_args, **_kwargs: None)

    assert run_workflow.execute_run(paths, prepared.run_id, stream_events=False) == 0

    with EventStore(paths.event_store) as store:
        started = [
            event for event in store.read_events(prepared.run_id) if event.type == "run.started"
        ]

    assert len(started) == 1
    title = started[0].payload_data["title"]
    assert title
    assert len(title) <= 60
    assert "deliberately long goal" in title
