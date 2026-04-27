# Mobius cold-start benchmarks

All measurements taken with `hyperfine --warmup 3 --runs 30` on darwin 24.6.0,
Python 3.14.3, against the `.venv/bin/mobius` console script in this repo.
Times are in milliseconds.

## v0.1.1 — cold-start regression fix (this release)

| Scenario                                | n  | p50  | p95   | p99   | budget  | status |
|-----------------------------------------|----|------|-------|-------|---------|--------|
| `mobius status` — fresh `MOBIUS_HOME`   | 30 | 73.9 | 109.3 | 115.0 | ≤ 116.4 | ✅     |
| `mobius status` — warm (existing DB)    | 30 | 65.1 |  76.0 |  80.4 | ≤ 116.4 | ✅     |
| `mobius status <id>` — warm fast path   | 30 | 61.9 |  72.9 | —     | ≤ 300   | ✅     |
| `mobius --help`                         | 20 | —    |  ~70  | —     | ≤ 150   | ✅     |
| `mobius --version`                      | 20 | —    |  ~80  | —     | ≤ 150   | ✅     |

## Before the fix (v0.1.0 smoke test, same machine)

| Scenario                                | mean   | range          | status |
|-----------------------------------------|--------|----------------|--------|
| `mobius status` — fresh `MOBIUS_HOME`   | 429.8  | 377 – 493      | ❌      |
| `mobius status` — warm                  | 356.8  | 346 – 376      | ❌      |

## What changed

The `mobius status` cold-start path used to import Typer, Rich, Pydantic v2,
and the entire `mobius.workflow.*` tree before reading a single row from the
event store. Profiling with `python -X importtime` showed Pydantic + Rich
alone accounted for ~120 ms of cumulative import time, plus ~30 ms for the
workflow tree.

`v0.1.1` adds a fast path in `src/mobius/cli/__init__.py` that handles
`mobius status` (no run id, no `--read-only`, no `--follow`) directly:

1. Resolve `MOBIUS_HOME` from env/`~/.mobius` using only stdlib.
2. If `events.db` is missing, perform a minimal inline bootstrap (CREATE
   TABLE statements + bootstrap event), so first-run still hits the budget.
3. Open the DB in `mode=ro` and check that `schema_migrations` already
   contains the latest version. If yes, read counts and emit the same
   payload as the slow path. If no, fall through to the slow path which
   applies migrations as before.

This keeps the slow (correct) path intact for any non-trivial flag and
preserves all 167 existing tests.

## Reproducing

```bash
# Warm
hyperfine --warmup 3 --runs 30 '.venv/bin/mobius status'

# Cold (empty MOBIUS_HOME on each run)
TMPHOME=$(mktemp -d)
hyperfine --warmup 3 --runs 30 \
  --prepare "find $TMPHOME -mindepth 1 -delete 2>/dev/null || true" \
  "MOBIUS_HOME=$TMPHOME .venv/bin/mobius status"
```

## CI regression guard

A dedicated GitHub Actions job (`.github/workflows/perf-guard.yml`,
`cold-start regression guard`) enforces a **hard budget** on every push to
`main` and on pull requests that touch `src/**` or `pyproject.toml`. Any
change that pushes the p95 above its budget fails CI.

### Tool choice — why `hyperfine`, not `pytest-benchmark`

`pytest-benchmark` measures **in-process callable timings** and runs in the
same Python interpreter as the test session. That is not what we want: the
whole point of the cold-start budget is the cost of spawning a fresh
`python` + importing `mobius` + running `main()` to exit. `hyperfine` spawns
the binary as a subprocess, which is exactly what an end-user pays. It also
has first-class support for `--warmup`, statistical outlier detection, and
machine-readable JSON export, so the assertion logic stays in a small
Python helper (`bench/ci_perf_guard.py`) without dragging in any new
runtime dependency.

### Methodology

For each invocation we run `hyperfine --warmup 3 --runs 30 --export-json`,
then `bench/ci_perf_guard.py` reads the JSON and computes the **p95** with
the nearest-rank method. The job fails as soon as any tracked p95 exceeds
its budget.

| Command          | CI p95 budget | Expected dev p95 (darwin-arm64) | CI factor |
|------------------|--------------:|--------------------------------:|----------:|
| `mobius --help`  |       ≤ 90 ms |                          ~60 ms |     ~1.5x |
| `mobius status`  |      ≤ 130 ms |                          ~85 ms |     ~1.5x |

The `1.5x` slack accounts for the GitHub-hosted `ubuntu-latest` runner
being noticeably slower and noisier than a local Apple Silicon dev box
(shared CPU, cold filesystem cache, no AOT-warm Python). Without the slack
we would see false negatives on otherwise-clean PRs.

### CI job shape (Linux only)

- Runner: `ubuntu-latest` (the budgets above are Linux p95s).
- Steps: build wheel → install into a fresh `.venv-perf` → seed
  `MOBIUS_HOME` once so `mobius status` exercises the warm fast path →
  benchmark with hyperfine → assert with `bench/ci_perf_guard.py`.
- Caching: `actions/setup-python` `cache: pip` and an `actions/cache`
  entry keyed on `pyproject.toml` + `uv.lock` for `.venv-perf`. End-to-end
  wall time is **under 2 minutes** on a warm cache (~75–110 s observed:
  ~5–10 s install + ~2 × 30 × 0.07 s hyperfine runs + overhead).
- The job also uploads both hyperfine `*.json` exports as a build
  artifact for post-mortem inspection.

### Reproducing locally

```bash
uv build --wheel
python -m venv /tmp/mobius-perf
/tmp/mobius-perf/bin/pip install dist/*.whl
NO_COLOR=1 hyperfine --warmup 3 --runs 30 --export-json /tmp/help.json \
  '/tmp/mobius-perf/bin/mobius --help'
NO_COLOR=1 hyperfine --warmup 3 --runs 30 --export-json /tmp/status.json \
  '/tmp/mobius-perf/bin/mobius status'
python bench/ci_perf_guard.py \
  --label "mobius --help"  --json /tmp/help.json   --budget-ms 90 \
  --label "mobius status"  --json /tmp/status.json --budget-ms 130
```

To confirm the guard fires on a regression, set
`MOBIUS_PERF_BUDGET_MULT=0.1` and rerun the last command — every budget is
multiplied by `0.1`, which makes any real measurement blow past it and the
script exits non-zero.

### Updating the budgets

If a deliberate change makes startup slower (e.g. a new mandatory feature),
update **both** the table above and the `HELP_BUDGET_MS` /
`STATUS_BUDGET_MS` env vars in `.github/workflows/perf-guard.yml` in the
same commit, and include the rationale in the PR description.

