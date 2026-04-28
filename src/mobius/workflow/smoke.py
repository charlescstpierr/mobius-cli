"""End-to-end workflow smoke test for the Mobius CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventStore

_SMOKE_TIMEOUT_SECONDS = 10.0
_STEP_TIMEOUT_SECONDS = 8.0


class SmokeStep(BaseModel):
    """One smoke-test step result."""

    model_config = ConfigDict(extra="forbid")

    name: str
    command: list[str]
    passed: bool
    duration_ms: int
    exit_code: int
    detail: str


class SmokeReport(BaseModel):
    """Structured report for ``mobius workflow smoke``."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    duration_ms: int
    workspace: str
    mobius_home: str
    run_id: str | None
    steps: list[SmokeStep]


@dataclass(frozen=True)
class _CommandResult:
    exit_code: int
    stdout: str
    stderr: str


def run_smoke(*, keep_workspace: bool = False) -> SmokeReport:
    """Run init -> interview -> seed -> run -> status -> qa in an isolated workspace."""
    workspace = Path(tempfile.gettempdir()) / f"mobius-smoke-{uuid.uuid4().hex}"
    mobius_home = workspace / ".mobius"
    fixture_path = workspace / "smoke-fixture.yaml"
    spec_path = workspace / "spec.yaml"
    start = time.monotonic()
    steps: list[SmokeStep] = []
    run_id: str | None = None

    env = {
        **os.environ,
        "MOBIUS_HOME": str(mobius_home),
        "NO_COLOR": "1",
        "MOBIUS_SMOKE_OFFLINE": "1",
    }
    command = os.environ.get("MOBIUS_SMOKE_COMMAND", "mobius")

    try:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        init_cmd = [command, "init", "--template", "blank", str(workspace)]
        _run_step("init", init_cmd, cwd=workspace.parent, env=env, steps=steps)

        fixture_path.write_text(_fixture_yaml(), encoding="utf-8")
        interview_cmd = [
            command,
            "interview",
            "--non-interactive",
            "--input",
            str(fixture_path),
            "--output",
            str(spec_path),
        ]
        _run_step("interview", interview_cmd, cwd=workspace, env=env, steps=steps)

        seed_cmd = [command, "seed", str(spec_path), "--json"]
        _run_step("seed", seed_cmd, cwd=workspace, env=env, steps=steps)

        run_cmd = [command, "run", "--foreground", "--spec", str(spec_path)]
        _run_step("run", run_cmd, cwd=workspace, env=env, steps=steps)

        if _can_continue(steps):
            run_id = _latest_run_id(mobius_home / "events.db")
            if run_id is None:
                _append_synthetic_failure(steps, "resolve_run_id", "no run session found")
            else:
                status_cmd = [command, "status", run_id, "--json"]
                _run_step("status", status_cmd, cwd=workspace, env=env, steps=steps)

                qa_cmd = [command, "qa", run_id, "--offline", "--json"]
                _run_step("qa", qa_cmd, cwd=workspace, env=env, steps=steps)
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)

    duration_ms = _elapsed_ms(start)
    passed = bool(steps) and all(step.passed for step in steps) and duration_ms < (
        _SMOKE_TIMEOUT_SECONDS * 1000
    )
    if duration_ms >= (_SMOKE_TIMEOUT_SECONDS * 1000):
        _append_synthetic_failure(
            steps,
            "duration",
            f"smoke exceeded {_SMOKE_TIMEOUT_SECONDS:.0f}s budget",
        )
        passed = False
    return SmokeReport(
        passed=passed,
        duration_ms=duration_ms,
        workspace=str(workspace),
        mobius_home=str(mobius_home),
        run_id=run_id,
        steps=steps,
    )


def _run_step(
    name: str,
    command: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    steps: list[SmokeStep],
) -> None:
    if not _can_continue(steps):
        return
    started = time.monotonic()
    try:
        result = _run_command(command, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as exc:
        steps.append(
            SmokeStep(
                name=name,
                command=list(command),
                passed=False,
                duration_ms=_elapsed_ms(started),
                exit_code=124,
                detail=f"timed out after {exc.timeout}s",
            )
        )
        return
    detail = _detail(result)
    steps.append(
        SmokeStep(
            name=name,
            command=list(command),
            passed=result.exit_code == 0,
            duration_ms=_elapsed_ms(started),
            exit_code=result.exit_code,
            detail=detail,
        )
    )


def _can_continue(steps: list[SmokeStep]) -> bool:
    return not steps or steps[-1].passed


def _run_command(command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> _CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=_STEP_TIMEOUT_SECONDS,
    )
    return _CommandResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _latest_run_id(event_store_path: Path) -> str | None:
    if not event_store_path.exists():
        return None
    with EventStore(event_store_path, read_only=True) as store:
        row = store.connection.execute(
            """
            SELECT session_id
            FROM sessions
            WHERE runtime = 'run'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
    return str(row["session_id"]) if row is not None else None


def _append_synthetic_failure(steps: list[SmokeStep], name: str, detail: str) -> None:
    steps.append(
        SmokeStep(
            name=name,
            command=[],
            passed=False,
            duration_ms=0,
            exit_code=1,
            detail=detail,
        )
    )


def _fixture_yaml() -> str:
    return "\n".join(
        [
            "project_type: greenfield",
            "template: blank",
            "goal: Verify the Mobius workflow smoke cycle completes offline.",
            "constraints:",
            "  - Use only local temporary files.",
            "  - Avoid LLMs, DNS, and network services.",
            "success:",
            "  - Init writes a workspace spec.",
            "  - Interview writes a deterministic spec.",
            "  - Seed, run, status, and QA all complete.",
            "",
        ]
    )


def _detail(result: _CommandResult) -> str:
    if result.exit_code == 0:
        return _last_non_empty_line(result.stdout) or _last_non_empty_line(result.stderr) or "ok"
    stdout = _last_non_empty_line(result.stdout)
    stderr = _last_non_empty_line(result.stderr)
    if stdout and stderr:
        return f"{stderr}; stdout={stdout}"
    return stderr or stdout or f"exit_code={result.exit_code}"


def _last_non_empty_line(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
