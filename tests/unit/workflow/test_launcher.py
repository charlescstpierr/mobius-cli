"""Unit tests for the shared worker launcher seam."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from mobius.config import MobiusPaths
from mobius.workflow.launcher import (
    WorkerConfig,
    WorkerLauncher,
    WorkerLaunchFailed,
    WorkerLaunchUsageError,
)


@dataclass(frozen=True)
class FakePreparedPaths:
    """Fake worker paths used by the test adapter."""

    log_file: Path


@dataclass(frozen=True)
class FakePrepared:
    """Fake prepared worker with the same interface as real prepared workers."""

    paths: FakePreparedPaths


def _paths(tmp_path: Path) -> MobiusPaths:
    return MobiusPaths(
        home=tmp_path,
        state_dir=tmp_path,
        event_store=tmp_path / "events.db",
        config_file=tmp_path / "config.json",
    )


def _config(
    prepared: FakePrepared,
    *,
    foreground_exit_code: int = 0,
    detached_pid: int = 1234,
) -> WorkerConfig[FakePrepared]:
    def _run_foreground(paths: MobiusPaths, worker: FakePrepared) -> int:
        assert paths.home == worker.paths.log_file.parent
        return foreground_exit_code

    def _start_detached(paths: MobiusPaths, worker: FakePrepared) -> int:
        assert paths.home == worker.paths.log_file.parent
        return detached_pid

    return WorkerConfig(
        name="fake",
        prepared=prepared,
        run_foreground=_run_foreground,
        start_detached=_start_detached,
        payload_factory=lambda worker, result: {
            "mode": result.mode,
            "pid": result.pid,
            "log": result.log,
            "name": worker.paths.log_file.name,
        },
        plain_output=lambda worker: worker.paths.log_file.name,
    )


def test_launch_foreground_overrides_detach_and_returns_foreground_result(
    tmp_path: Path,
) -> None:
    prepared = FakePrepared(paths=FakePreparedPaths(log_file=tmp_path / "log"))
    result = WorkerLauncher(_paths(tmp_path)).launch(
        _config(prepared),
        detach=True,
        foreground=True,
    )

    assert result.mode == "foreground"
    assert result.pid is None
    assert result.log == str(tmp_path / "log")


def test_launch_detached_returns_pid_without_running_subprocess(tmp_path: Path) -> None:
    prepared = FakePrepared(paths=FakePreparedPaths(log_file=tmp_path / "log"))
    result = WorkerLauncher(_paths(tmp_path)).launch(
        _config(prepared, detached_pid=9876),
        detach=True,
        foreground=False,
    )

    assert result.mode == "detach"
    assert result.pid == 9876
    assert result.log == str(tmp_path / "log")


def test_launch_rejects_missing_lifecycle(tmp_path: Path) -> None:
    prepared = FakePrepared(paths=FakePreparedPaths(log_file=tmp_path / "log"))

    with pytest.raises(WorkerLaunchUsageError, match="fake requires"):
        WorkerLauncher(_paths(tmp_path)).launch(
            _config(prepared),
            detach=False,
            foreground=False,
        )


def test_launch_foreground_nonzero_exit_raises_exit_code(tmp_path: Path) -> None:
    prepared = FakePrepared(paths=FakePreparedPaths(log_file=tmp_path / "log"))

    with pytest.raises(WorkerLaunchFailed) as exc:
        WorkerLauncher(_paths(tmp_path)).launch(
            _config(prepared, foreground_exit_code=7),
            detach=False,
            foreground=True,
        )

    assert exc.value.exit_code == 7
