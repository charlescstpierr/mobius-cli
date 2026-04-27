"""CI cold-start regression guard.

Reads hyperfine JSON export(s) and fails if the p95 of any tracked command
exceeds its budget. Budgets are intentionally calibrated for the
``ubuntu-latest`` GitHub runner (~1.5x slower than a local dev box).

Usage::

    python bench/ci_perf_guard.py \\
        --label "mobius --help" --json help.json --budget-ms 90 \\
        --label "mobius status" --json status.json --budget-ms 130

Exit code is 0 when every measured p95 is at or below its budget, 1
otherwise. Override ``MOBIUS_PERF_BUDGET_MULT`` to tighten or relax all
budgets uniformly (used in local dry-runs to confirm the guard fires).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Check:
    label: str
    json_path: Path
    budget_ms: float


def percentile(samples: Sequence[float], pct: float) -> float:
    if not samples:
        msg = "cannot compute percentile of empty sample"
        raise ValueError(msg)
    ordered = sorted(samples)
    rank = math.ceil((pct / 100.0) * len(ordered))
    index = min(max(rank - 1, 0), len(ordered) - 1)
    return ordered[index]


def load_times_ms(path: Path) -> list[float]:
    payload = json.loads(path.read_text())
    results = payload.get("results")
    if not results:
        msg = f"{path}: no 'results' array in hyperfine JSON"
        raise ValueError(msg)
    times_seconds = results[0].get("times")
    if not times_seconds:
        msg = f"{path}: no 'times' samples in first result"
        raise ValueError(msg)
    return [float(t) * 1000.0 for t in times_seconds]


def parse_args(argv: Sequence[str]) -> list[Check]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--json", action="append", required=True, type=Path)
    parser.add_argument("--budget-ms", action="append", required=True, type=float)
    args = parser.parse_args(argv)
    if not (len(args.label) == len(args.json) == len(args.budget_ms)):
        parser.error("--label, --json, and --budget-ms must be repeated together")
    return [
        Check(label=label, json_path=jpath, budget_ms=budget)
        for label, jpath, budget in zip(args.label, args.json, args.budget_ms, strict=True)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    checks = parse_args(list(sys.argv[1:] if argv is None else argv))
    multiplier = float(os.environ.get("MOBIUS_PERF_BUDGET_MULT", "1.0"))
    failed = 0
    for check in checks:
        samples = load_times_ms(check.json_path)
        p50 = percentile(samples, 50)
        p95 = percentile(samples, 95)
        p99 = percentile(samples, 99)
        budget = check.budget_ms * multiplier
        status = "OK" if p95 <= budget else "FAIL"
        print(
            f"[{status}] {check.label}: n={len(samples)} "
            f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms "
            f"budget={budget:.1f}ms"
        )
        if status == "FAIL":
            failed += 1
            print(
                f"  -> regression: p95 {p95:.1f}ms exceeds budget {budget:.1f}ms",
                file=sys.stderr,
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
