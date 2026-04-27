# Migration from Ouroboros MCP Tools

Mobius replaces Ouroboros MCP tool calls with direct shell commands. The new
contract is: invoke `mobius ...`, read command data from stdout, and read logs or
progress from stderr.

## Tool mapping

| Ouroboros MCP tool | Mobius replacement | Notes |
| --- | --- | --- |
| `ouroboros_interview` | `mobius interview --non-interactive --input <fixture> --output <spec.yaml>` | Produces a spec without MCP stdio. |
| `ouroboros_pm_interview` | `mobius interview --non-interactive --input <fixture> --output <spec.yaml>` | Product-manager interview mode maps to the same spec-generation surface. |
| `ouroboros_generate_seed` | `mobius seed <spec.yaml>` | Validates a spec and persists seed events. Add `--json` for structured output. |
| `ouroboros_execute_seed` | `mobius run --foreground --spec <spec.yaml>` | Foreground execution preserves blocking behavior while streaming events to stderr. |
| `ouroboros_start_execute_seed` | `mobius run --spec <spec.yaml>` | Detached by default; stdout is the run id. |
| `ouroboros_session_status` | `mobius status <run_id>` | Use `--json` for machine-readable status. |
| `ouroboros_job_status` | `mobius status <run_id>` | Detached run/evolution status is now part of the session status surface. |
| `ouroboros_job_wait` | `mobius status <run_id> --follow` | Streams updates until the session reaches a terminal state. |
| `ouroboros_job_result` | `mobius status <run_id> --json` | Final state and timestamps are read from the event store. |
| `ouroboros_cancel_job` | `mobius cancel <run_id>` | Cancels detached runs and evolutions by persisted session id. |
| `ouroboros_cancel_execution` | `mobius cancel <run_id> --grace-period <seconds>` | Sends SIGTERM, escalates after the grace period, and removes PID metadata. |
| `ouroboros_query_events` | `mobius status <run_id> --json` or `mobius ac-tree <run_id> --json` | Mobius exposes curated status/tree views instead of raw MCP event queries. |
| `ouroboros_ac_dashboard` | `mobius ac-tree <run_id>` | Compact markdown acceptance-criteria tree. |
| `ouroboros_ac_tree_hud` | `mobius ac-tree <run_id> --json` | Structured `nodes[]` and `edges[]` for HUD-style consumers. |
| `ouroboros_qa` | `mobius qa <run_id> --offline` | Deterministic local QA; add `--json` for summaries and result rows. |
| `ouroboros_evaluate` | `mobius qa <run_id> --offline` | Evaluation is represented as QA verdicts in the current CLI. |
| `ouroboros_checklist_verify` | `mobius qa <run_id> --offline --json` | Checklist pass/fail details are returned in `results[]`. |
| `ouroboros_measure_drift` | `mobius qa <run_id> --offline --json` | Current drift-like checks are surfaced as deterministic QA findings. |
| `ouroboros_lateral_think` | `mobius evolve --from <run_id>` | Alternative exploration is folded into the evolution loop. |
| `ouroboros_evolve_step` | `mobius evolve --from <run_id> --foreground --generations 1` | One blocking generation step. |
| `ouroboros_start_evolve_step` | `mobius evolve --from <run_id> --generations <n>` | Detached by default; stdout is the evolution id. |
| `ouroboros_lineage_status` | `mobius lineage <id>` | Use `--json` for `ancestors[]` and `descendants[]`. |
| `ouroboros_evolve_rewind` | `mobius lineage <id> --hash` plus a new run/evolve command | Mobius does not mutate history in place; use lineage to select a prior aggregate and start a new command. |
| `ouroboros_brownfield` | `mobius interview --non-interactive --input <brownfield-fixture> --output <spec.yaml>` | Brownfield context is represented in the spec fixture with `project_type: brownfield` and `context`. |

## Agent invocation changes

Old agents called MCP tools by name. New agents should shell out:

```bash
mobius run --spec spec.yaml
mobius status "$run_id" --follow
mobius qa "$run_id" --offline --json
```

`mobius setup --runtime claude|codex|hermes` installs skills and command files
that teach agents to use the CLI. It never writes an MCP server registration.
