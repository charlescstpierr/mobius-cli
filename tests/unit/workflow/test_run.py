from pathlib import Path

import pytest

from mobius.config import get_paths
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

    assert prepared.run_id.startswith("run_")
    assert prepared.spec.goal == "Execute a run from a validated spec."
    assert prepared.paths.metadata_file.exists()
    assert str(spec.resolve()) in prepared.paths.metadata_file.read_text(encoding="utf-8")
    assert get_run_paths(paths, prepared.run_id).directory == prepared.paths.directory


def test_prepare_run_rejects_invalid_spec(tmp_path: Path) -> None:
    spec = tmp_path / "invalid.yaml"
    spec.write_text("project_type: greenfield\ngoal:\nconstraints:\nsuccess_criteria:\n")

    with pytest.raises(SeedSpecValidationError):
        prepare_run(get_paths(tmp_path / "home"), spec)
