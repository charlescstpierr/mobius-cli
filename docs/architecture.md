# Mobius Architecture

Repository: <https://github.com/charlescstpierr/mobius-cli>

Mobius is a CLI-only workflow runtime. Every public operation is a short-lived
process, and long-running work is delegated to detached worker subprocesses whose
state is recoverable from SQLite.

## Lazy import strategy

The console entry point is `mobius = "mobius.cli:main"`. `src/mobius/cli/__init__.py`
implements fast paths for latency-sensitive commands:

- `mobius --help`
- `mobius --version`
- `mobius status` (with or without a run id, when neither `--follow` nor
  `--read-only` is set)
- `mobius init [PATH]` — workspace scaffolding introduced in `v0.1.1`

Those paths avoid importing Typer/Rich and avoid loading workflow modules. For
all other commands, `src/mobius/cli/main.py` registers lightweight Typer command
functions that import `mobius.cli.commands.<name>` only after the specific
subcommand is selected. Heavy workflow logic therefore stays out of the
`--help` cold path.

## Command layer

The command layer is responsible for:

1. Parsing CLI arguments and flags.
2. Translating validation or not-found failures into documented exit codes.
3. Writing command data to stdout through `mobius.cli.output`.
4. Sending diagnostics and progress to stderr.

Command modules delegate domain work to `src/mobius/workflow/` and persistence
work to `src/mobius/persistence/`.

## Detached worker pattern

`mobius run` and `mobius evolve` detach by default:

1. The parent validates inputs and creates run/evolution metadata under
   `$MOBIUS_HOME`.
2. The parent creates or updates the SQLite session row.
3. The parent starts `mobius _worker run <id>` or `mobius _worker evolve <id>`.
4. The worker writes progress events transactionally to SQLite.
5. The worker writes its PID to a per-session PID file and removes it on normal
   exit or handled cancellation.
6. `mobius status <id>` marks stale PID files as crashed when a PID file points
   at a dead process.

There is no daemon and no MCP stdio server. Each command can be retried by
re-reading the event store.

## Workspace bootstrap

`mobius init [PATH]` (added in `v0.1.1`) writes a starter `spec.yaml` into the
target directory and initializes the Mobius event store inline so a fresh
checkout can run `mobius run --spec spec.yaml` without any further setup. The
inline bootstrap reuses the same fast path as `mobius status` against an empty
`MOBIUS_HOME`, so initialization stays under the cold-start budget documented
in [`benchmarks.md`](benchmarks.md).

## Filesystem layout

The state root defaults to `~/.mobius` and can be relocated with `MOBIUS_HOME`.

```text
$MOBIUS_HOME/
├── events.db
├── runs/<run_id>/
│   ├── pid
│   ├── log
│   └── metadata.json
└── evolutions/<evolution_id>/
    ├── pid
    ├── log
    └── metadata.json
```

Runtime directories are created with `0700` permissions and the SQLite database
is created with `0600` permissions.

## Event store schema

SQLite is the source of truth. Every connection applies:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
```

Core tables:

| Table | Purpose |
| --- | --- |
| `events` | Append-only event log with `event_id`, `aggregate_id`, contiguous `sequence`, `type`, JSON `payload`, and UTC `created_at`. |
| `sessions` | Run, seed, interview, QA, and evolution session lifecycle with `started_at`, `ended_at`, `runtime`, metadata, and status. |
| `aggregates` | Latest aggregate sequence and snapshot metadata for replay/hash operations. |
| `schema_migrations` | Applied migration versions and timestamps. |

The `events` table has a unique `(aggregate_id, sequence)` index so concurrent
writers cannot create duplicate sequence positions. Event payloads are canonical
JSON strings, and timestamps use ISO-8601 UTC with a `Z` suffix.

## Recovery invariants

- WAL mode and `busy_timeout=30000` are applied on every open.
- Stale PID files are reconciled through `mobius status`.
- Terminal states include `completed`, `failed`, `crashed`, `cancelled`, and
  `interrupted`.
- `cancel` checks persisted session state before signalling a PID.
- Read-only status uses SQLite URI `mode=ro` to avoid WAL writes.

## Agent integration

Agent assets under `skills/` and `.claude/commands/` instruct agents to invoke
`mobius` via shell commands. `mobius setup` copies those assets into runtime
locations for Claude, Codex, or Hermes and intentionally never registers an MCP server.
