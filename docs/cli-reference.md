# Mobius CLI Reference

Mobius is invoked as `mobius [OPTIONS] COMMAND [ARGS]...`.

## Global options

| Option | Description |
| --- | --- |
| `--json` | Emit machine-readable JSON for commands that support structured output. |
| `--version` | Print `mobius <version>` and exit. |
| `-h`, `--help` | Print help. Supported by every public command and subcommand. |

## Exit codes

| Code | Name | Meaning |
| --- | --- | --- |
| `0` | ok | Command completed successfully. |
| `1` | generic error | Unexpected runtime error or persistence failure. |
| `2` | usage error | Invalid command shape, missing required argument, or incompatible options. |
| `3` | validation error | User input was understood but failed Mobius validation. |
| `4` | not found | Requested run, evolution, aggregate, or config key does not exist. |
| `130` | interrupted | Foreground command received SIGINT and shut down cleanly. |

## Commands

### `mobius interview`

Run a deterministic project interview and render a project spec.

```text
Usage: mobius interview [OPTIONS]
```

Flags:

- `--non-interactive` — read deterministic answers from `--input` instead of prompting or using an LLM.
- `--input FILE` — fixture file containing interview answers.
- `--output FILE` — destination for the generated spec YAML.
- `-h`, `--help` — print command help.

### `mobius seed`

Create a seed session from a spec file or interview session id.

```text
Usage: mobius seed [OPTIONS] SPEC_OR_SESSION_ID
```

Arguments and flags:

- `SPEC_OR_SESSION_ID` — path to a project spec file, or an interview session id.
- `--json` — emit `{"session_id": ..., "event_count": ...}`.
- `-h`, `--help` — print command help.

### `mobius run`

Execute a seed spec. Detached mode is the default.

```text
Usage: mobius run [OPTIONS]
```

Flags:

- `--spec FILE` — required seed spec file to execute.
- `--detach` — start a background worker and immediately print the run id. Defaults to `True`.
- `--foreground` — run in the current process and stream events to stderr.
- `-h`, `--help` — print command help.

### `mobius status`

Show event-store health or a run/evolution status snapshot.

```text
Usage: mobius status [OPTIONS] [RUN_ID]
```

Arguments and flags:

- `RUN_ID` — optional run or evolution id to inspect. Omit it for store health.
- `--read-only` — open SQLite with `mode=ro` and avoid WAL writes.
- `--json` — emit structured status JSON.
- `--follow` — poll every 200 ms and stream event deltas until a terminal state.
- `-h`, `--help` — print command help.

### `mobius ac-tree`

Print a compact acceptance-criteria tree for a run.

```text
Usage: mobius ac-tree [OPTIONS] RUN_ID
```

Arguments and flags:

- `RUN_ID` — run id to visualize.
- `--json` — emit `nodes[]` and `edges[]`.
- `--cursor INTEGER` — only include event delta nodes after this sequence. Default: `0`.
- `--max-nodes INTEGER` — maximum nodes before adding a truncation marker. Default: `50`; minimum: `5`.
- `-h`, `--help` — print command help.

### `mobius qa`

Run deterministic QA checks for a run.

```text
Usage: mobius qa [OPTIONS] RUN_ID
```

Arguments and flags:

- `RUN_ID` — run id to judge.
- `--offline` — use local heuristics without LLM or network calls. Defaults to `True`.
- `--json` — emit `summary` and `results`.
- `-h`, `--help` — print command help.

### `mobius cancel`

Cancel a detached run or evolution.

```text
Usage: mobius cancel [OPTIONS] RUN_ID
```

Arguments and flags:

- `RUN_ID` — run or evolution id to cancel.
- `--grace-period FLOAT` — seconds to wait after SIGTERM before SIGKILL. Default: `10.0`; minimum: `0.0`.
- `-h`, `--help` — print command help.

### `mobius evolve`

Run a generation evolution loop. Detached mode is the default.

```text
Usage: mobius evolve [OPTIONS]
```

Flags:

- `--from TEXT` — required completed run id to use as the evolution source.
- `--generations INTEGER` — maximum generation count, hard-capped at 30. Default: `30`; minimum: `1`.
- `--detach` — start a background worker and immediately print the evolution id. Defaults to `True`.
- `--foreground` — run in the current process and stream generation events to stderr.
- `-h`, `--help` — print command help.

### `mobius lineage`

Print lineage or a deterministic replay hash for an aggregate.

```text
Usage: mobius lineage [OPTIONS] [AGGREGATE_ID]
```

Arguments and flags:

- `AGGREGATE_ID` — optional aggregate id to inspect.
- `--json` — emit `ancestors[]` and `descendants[]`.
- `--hash` — print the deterministic SHA-256 replay hash.
- `--aggregate TEXT` — aggregate id to hash or inspect; alias for the positional id.
- `-h`, `--help` — print command help.

### `mobius setup`

Install or remove Mobius agent integration assets without registering MCP.

```text
Usage: mobius setup [OPTIONS]
```

Flags:

- `--runtime TEXT` — required runtime: `claude`, `codex`, or `hermes`.
- `--scope TEXT` — installation scope: `user` or `project`. Default: `user`.
- `--dry-run` — print planned actions without filesystem writes.
- `--uninstall` — remove only assets previously installed by Mobius.
- `-h`, `--help` — print command help.

### `mobius config`

Show, get, and set Mobius configuration.

```text
Usage: mobius config [OPTIONS] COMMAND [ARGS]...
```

Flags:

- `-h`, `--help` — print command help.

#### `mobius config show`

```text
Usage: mobius config show [OPTIONS]
```

- `--json` — emit paths, values, and SQLite `busy_timeout`.
- `-h`, `--help` — print command help.

#### `mobius config get`

```text
Usage: mobius config get [OPTIONS] KEY
```

- `KEY` — config key to read.
- `--json` — emit a key/value object.
- `-h`, `--help` — print command help.

#### `mobius config set`

```text
Usage: mobius config set [OPTIONS] KEY VALUE
```

- `KEY` — config key to persist.
- `VALUE` — config value to persist.
- `--json` — emit a key/value object.
- `-h`, `--help` — print command help.
