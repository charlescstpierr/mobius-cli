# Mobius v0.1.4 — Multi-project UAT

**Date:** 2026-04-27
**Wheel:** `mobius-0.1.4-py3-none-any.whl`
**Verdict:** ✅ 6 / 6 project types pass.

## What this UAT exercises

For each of the six built-in project templates we run an end-to-end loop on
the published wheel:

```sh
mobius init --template <name>          # scaffold spec.yaml
mobius run --spec spec.yaml --foreground
mobius status <run_id> --json
mobius runs ls
mobius cancel <run_id>                  # idempotency on a completed run
```

| #   | Template | `init` | foreground `run` | `status --json` | `runs ls` | idempotent `cancel` | Verdict |
| --- | -------- | ------ | ---------------- | --------------- | --------- | ------------------- | ------- |
| 1   | web      | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |
| 2   | cli      | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |
| 3   | lib      | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |
| 4   | etl      | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |
| 5   | mobile   | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |
| 6   | docs     | ✅     | ✅ completed     | ✅              | ✅        | ✅                  | ✅      |

Each `mobius run --foreground` emitted `run.started`, several
`run.progress`, and exactly one `run.completed`. The session row
transitioned `running → completed`. A subsequent `mobius cancel` returned
`already finished <run_id>` and did **not** insert a duplicate
`run.cancelled` event — fixing the v0.1.3 regression.

## v0.1.3 → v0.1.4 deltas confirmed in the field

| v0.1.3 issue                                                         | v0.1.4 outcome                                                |
| -------------------------------------------------------------------- | -------------------------------------------------------------- |
| Two `run.cancelled` events per cancel call                           | Exactly one (worker is sole authority; cancel command observes) |
| `key 'X' cannot contain both scalar and …` for unknown spec keys     | `unknown spec key: 'X'. Allowed top-level keys: …`              |
| No `mobius runs ls`                                                  | Implemented (Markdown table + `--json` envelope)                |
| `mobius init` had no project templates                               | 6 templates + `blank`, with cwd auto-detect                     |
| `mobius interview` shallow / required fixtures                       | Interactive driver by default with template-backed defaults     |
| No `steps:`/`matrix:`/`metadata:`/`template:` in spec model          | All four are validated, first-class top-level keys              |

## Sample run (template=etl)

```text
2026-04-27T23:02:11.999Z run.started     {"goal":"Run nightly ETL pipeline producing validated load artifacts.", "spec_path":"/tmp/proj-etl/spec.yaml"}
2026-04-27T23:02:12.001Z run.progress    {"step":1,"total":7}
…
2026-04-27T23:02:13.437Z run.completed   {"constraint_count":3,"success_criteria_count":4}

$ mobius status run_98e190236efc --json
{"run_id":"run_98e190236efc","state":"completed","started_at":"2026-04-27T23:02:12.003858Z","last_event_at":"2026-04-27T23:02:13.437245Z"}

$ mobius runs ls
| Run id           | Runtime | State     | Started at                | Last event                |
| ---              | ---     | ---       | ---                       | ---                       |
| run_98e190236efc | run     | completed | 2026-04-27T23:02:12.003Z  | 2026-04-27T23:02:13.437Z  |

$ mobius cancel run_98e190236efc
already finished run_98e190236efc
```

## Coverage / quality gates at release

- Tests: **463 passed**, 0 failed.
- Coverage: **95.43 %** (gate: 95 %).
- Type-check: `mypy --strict src` → no issues.
- Lint: `ruff check src tests` → all checks passed.
- Lint format: `ruff format src tests` → clean.

Mobius v0.1.4 ships green across every UAT scenario the v0.1.3 report
flagged. ✅
