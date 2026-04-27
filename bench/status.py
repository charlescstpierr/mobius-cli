"""Benchmark Mobius CLI cold-start latency for ``mobius status <id>``."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from mobius.persistence.event_store import EventStore

ITERATIONS = 50
THRESHOLD_SECONDS = 0.300
FIXTURE_RUN_ID = "run_bench_status_fixture"
FORCE_FAIL_ENV = "MOBIUS_BENCH_FORCE_FAIL"


class BenchmarkError(RuntimeError):
    """Raised when the benchmark command cannot be measured successfully."""


def percentile(samples: Sequence[float], percentile_value: float) -> float:
    """Return the nearest-rank percentile from a non-empty sample set."""
    if not samples:
        msg = "cannot compute percentile for an empty sample set"
        raise ValueError(msg)
    rank = math.ceil((percentile_value / 100.0) * len(samples))
    index = min(max(rank - 1, 0), len(samples) - 1)
    return sorted(samples)[index]


def create_status_fixture(mobius_home: Path, run_id: str = FIXTURE_RUN_ID) -> str:
    """Create a completed run row that ``mobius status <id>`` can read."""
    mobius_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(mobius_home, 0o700)
    with EventStore(mobius_home / "events.db") as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"benchmark": True},
            status="running",
        )
        store.append_event(run_id, "run.started", {"benchmark": True})
        store.append_event(run_id, "run.completed", {"benchmark": True})
        store.end_session(run_id, status="completed")
    return run_id


def measure_once(command: Sequence[str], env: Mapping[str, str], *, force_fail: bool) -> float:
    """Run one benchmark iteration and return elapsed wall time in seconds."""
    started = time.perf_counter()
    result = subprocess.run(
        list(command),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(env),
    )
    if force_fail:
        time.sleep(THRESHOLD_SECONDS + 0.020)
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = f"benchmark command failed with exit {result.returncode}: {stderr}"
        raise BenchmarkError(msg)
    return elapsed


def run_benchmark(
    *,
    iterations: int = ITERATIONS,
    threshold_seconds: float = THRESHOLD_SECONDS,
    env: Mapping[str, str] | None = None,
    mobius_home: Path | None = None,
) -> tuple[list[float], int]:
    """Measure ``mobius status <fixture_id>`` repeatedly and return samples and exit code."""
    if iterations <= 0:
        msg = "iterations must be positive"
        raise ValueError(msg)
    benchmark_env = dict(os.environ if env is None else env)
    benchmark_env.setdefault("NO_COLOR", "1")
    force_fail = benchmark_env.get(FORCE_FAIL_ENV) == "1"

    if mobius_home is None:
        with tempfile.TemporaryDirectory(prefix="mobius-bench-status-") as temp_dir:
            return _run_with_home(
                iterations=iterations,
                threshold_seconds=threshold_seconds,
                env=benchmark_env,
                force_fail=force_fail,
                mobius_home=Path(temp_dir),
            )
    return _run_with_home(
        iterations=iterations,
        threshold_seconds=threshold_seconds,
        env=benchmark_env,
        force_fail=force_fail,
        mobius_home=mobius_home,
    )


def _run_with_home(
    *,
    iterations: int,
    threshold_seconds: float,
    env: dict[str, str],
    force_fail: bool,
    mobius_home: Path,
) -> tuple[list[float], int]:
    run_id = create_status_fixture(mobius_home)
    env["MOBIUS_HOME"] = str(mobius_home)
    command = ("mobius", "status", run_id)
    samples = [measure_once(command, env, force_fail=force_fail) for _ in range(iterations)]
    p95 = percentile(samples, 95)
    return samples, 1 if p95 > threshold_seconds else 0


def _format_ms(value: float) -> str:
    return f"{value * 1000:.1f}ms"


def main() -> int:
    """Run the benchmark and return a CI-friendly exit code."""
    try:
        samples, exit_code = run_benchmark()
    except (BenchmarkError, ValueError) as exc:
        print(f"status: {exc}", file=sys.stderr)
        return 1

    p50 = percentile(samples, 50)
    p95 = percentile(samples, 95)
    p99 = percentile(samples, 99)
    threshold_ms = _format_ms(THRESHOLD_SECONDS)
    print(
        "status "
        f"iterations={len(samples)} "
        f"p50={_format_ms(p50)} "
        f"p95={_format_ms(p95)} "
        f"p99={_format_ms(p99)} "
        f"threshold={threshold_ms}"
    )
    if exit_code != 0:
        print(f"status p95 {_format_ms(p95)} exceeds threshold {threshold_ms}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
