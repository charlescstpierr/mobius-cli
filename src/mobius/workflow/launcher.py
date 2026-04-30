"""Worker lifecycle launcher shared by CLI adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mobius.config import MobiusPaths


class PreparedWorkerPaths(Protocol):
    """Filesystem paths exposed by a prepared worker adapter."""

    @property
    def log_file(self) -> Path:
        """Worker stderr log path."""
        ...


class PreparedWorker(Protocol):
    """Prepared worker object accepted by the launcher seam."""

    @property
    def paths(self) -> PreparedWorkerPaths:
        """Filesystem paths for the prepared worker."""
        ...


@dataclass(frozen=True)
class WorkerConfig[PreparedT: PreparedWorker]:
    """Adapter configuration for a prepared foreground/detached worker."""

    name: str
    prepared: PreparedT
    run_foreground: Callable[[MobiusPaths, PreparedT], int]
    start_detached: Callable[[MobiusPaths, PreparedT], int]
    payload_factory: Callable[[PreparedT, WorkerLaunchResult], Mapping[str, object]]
    plain_output: Callable[[PreparedT], str]
    success_exit_code: int = 0


@dataclass(frozen=True)
class WorkerLaunchResult:
    """Result of a worker lifecycle launch."""

    mode: Literal["foreground", "detach"]
    pid: int | None
    log: str


class PreparedRunWorker(PreparedWorker, Protocol):
    """Prepared run fields needed for CLI launch output."""

    @property
    def run_id(self) -> str:
        """Run identifier."""
        ...


class PreparedEvolutionWorker(PreparedWorker, Protocol):
    """Prepared evolution fields needed for CLI launch output."""

    @property
    def evolution_id(self) -> str:
        """Evolution identifier."""
        ...

    @property
    def source_run_id(self) -> str:
        """Source run identifier."""
        ...

    @property
    def generations(self) -> int:
        """Configured generation count."""
        ...


class WorkerLaunchUsageError(ValueError):
    """Raised when a launcher invocation selects no supported lifecycle."""


class WorkerLaunchFailed(RuntimeError):
    """Raised when foreground execution returns a non-zero exit code."""

    def __init__(self, exit_code: int) -> None:
        super().__init__(f"worker exited with status {exit_code}")
        self.exit_code = exit_code


class WorkerLauncher:
    """Launch prepared workers through one foreground/detach lifecycle seam."""

    def __init__(self, paths: MobiusPaths) -> None:
        self._paths = paths

    def launch[PreparedT: PreparedWorker](
        self,
        config: WorkerConfig[PreparedT],
        *,
        detach: bool,
        foreground: bool,
    ) -> WorkerLaunchResult:
        """Launch ``config`` in foreground or detached mode."""
        if foreground and detach:
            detach = False

        if foreground:
            exit_code = config.run_foreground(self._paths, config.prepared)
            if exit_code != config.success_exit_code:
                raise WorkerLaunchFailed(exit_code)
            return WorkerLaunchResult(
                mode="foreground",
                pid=None,
                log=str(config.prepared.paths.log_file),
            )

        if not detach:
            raise WorkerLaunchUsageError(
                f"{config.name} requires either --detach or --foreground"
            )

        pid = config.start_detached(self._paths, config.prepared)
        return WorkerLaunchResult(
            mode="detach",
            pid=pid,
            log=str(config.prepared.paths.log_file),
        )

    def launch_for_cli[PreparedT: PreparedWorker](
        self,
        config: WorkerConfig[PreparedT],
        *,
        detach: bool,
        foreground: bool,
        json_output: bool,
        usage_exit_code: int,
    ) -> None:
        """Launch a worker and emit the CLI result for detached mode."""
        import typer

        from mobius.cli import output

        try:
            result = self.launch(config, detach=detach, foreground=foreground)
        except WorkerLaunchUsageError as exc:
            output.write_error_line(str(exc))
            raise typer.Exit(code=usage_exit_code) from exc
        except WorkerLaunchFailed as exc:
            raise typer.Exit(code=exc.exit_code) from exc

        if result.mode == "foreground":
            return

        if json_output:
            payload = config.payload_factory(config.prepared, result)
            output.write_json(json.dumps(payload, separators=(",", ":")))
            return
        output.write_line(config.plain_output(config.prepared))


def run_worker_config[RunWorkerT: PreparedRunWorker](
    prepared: RunWorkerT,
    *,
    run_foreground: Callable[[MobiusPaths, RunWorkerT], int],
    start_detached: Callable[[MobiusPaths, RunWorkerT], int],
    success_exit_code: int,
) -> WorkerConfig[RunWorkerT]:
    """Build the real run worker adapter for the launcher seam."""
    return WorkerConfig(
        name="run",
        prepared=prepared,
        run_foreground=run_foreground,
        start_detached=start_detached,
        payload_factory=lambda worker, result: {
            "run_id": worker.run_id,
            "mode": result.mode,
            "pid": result.pid,
            "log": result.log,
        },
        plain_output=lambda worker: worker.run_id,
        success_exit_code=success_exit_code,
    )


def evolution_worker_config[EvolutionWorkerT: PreparedEvolutionWorker](
    prepared: EvolutionWorkerT,
    *,
    run_foreground: Callable[[MobiusPaths, EvolutionWorkerT], int],
    start_detached: Callable[[MobiusPaths, EvolutionWorkerT], int],
    success_exit_code: int,
) -> WorkerConfig[EvolutionWorkerT]:
    """Build the real evolution worker adapter for the launcher seam."""
    return WorkerConfig(
        name="evolve",
        prepared=prepared,
        run_foreground=run_foreground,
        start_detached=start_detached,
        payload_factory=lambda worker, result: {
            "evolution_id": worker.evolution_id,
            "source_run_id": worker.source_run_id,
            "mode": result.mode,
            "generations": worker.generations,
            "pid": result.pid,
            "log": result.log,
        },
        plain_output=lambda worker: worker.evolution_id,
        success_exit_code=success_exit_code,
    )
