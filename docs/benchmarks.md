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
