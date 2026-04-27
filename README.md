# Mobius

[![CI](https://github.com/charlescstpierr/mobius-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/charlescstpierr/mobius-cli/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A595%25-brightgreen.svg)](docs/benchmarks.md)
[![PyPI](https://img.shields.io/badge/pypi-pending-lightgrey.svg)](https://github.com/charlescstpierr/mobius-cli/releases)
[![License](https://img.shields.io/github/license/charlescstpierr/mobius-cli)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

See [`CHANGELOG.md`](CHANGELOG.md) for release notes,
[`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup,
and [`SECURITY.md`](SECURITY.md) for vulnerability reporting.

Repository: <https://github.com/charlescstpierr/mobius-cli>

Mobius is a from-scratch Python CLI rewrite inspired by
[Q00/ouroboros](https://github.com/Q00/ouroboros). It keeps the interview,
seed, execution, QA, and evolution workflow ideas, but exposes them as fast
one-shot shell commands instead of a long-running MCP server.

> **What Mobius IS** — a fast, MCP-free **acceptance-criteria event tracker**
> with first-class lineage, replay, and per-project state isolation. You
> describe a project in `spec.yaml`; Mobius records every change as an event
> and gives you a queryable history.
>
> **What Mobius IS NOT** — a build runner, task scheduler, or pipeline
> executor. It does **not** execute the commands you describe. Bring your
> own runner (Make, npm, cargo, dbt, fastlane, your CI, your agent). Mobius
> tracks the *what* and the *whether*; you bring the *how*.

## Install

Pick whichever installer you already use:

- **`pip`** (no extra tools required) — install the latest release wheel
  directly from GitHub:

  ```sh
  pip install https://github.com/charlescstpierr/mobius-cli/releases/latest/download/mobius-0.1.3-py3-none-any.whl
  ```

  Replace the version in the URL with the [release](https://github.com/charlescstpierr/mobius-cli/releases)
  you want, or download the wheel and run `pip install ./mobius-0.1.3-py3-none-any.whl`.

- **`uv`** — `uv tool install git+https://github.com/charlescstpierr/mobius-cli`
- **`pipx`** — `pipx install git+https://github.com/charlescstpierr/mobius-cli`

### State directory

Mobius stores all session state in a SQLite event store at
`$MOBIUS_HOME/events.db`. When `MOBIUS_HOME` is not set the default is
`~/.mobius/events.db` (a global path **shared across every Mobius project**).
Set `MOBIUS_HOME` per-project — for example `export MOBIUS_HOME="$PWD/.mobius"`
— if you want each workspace to have its own event store. `mobius init` prints
the resolved path on first run; `mobius config get event_store` returns it any
time.

## Quickstart

Run these blocks from the repository root. They install the `mobius` command
and exercise the CLI end-to-end in an isolated state directory.

```bash
uv tool install . --force
```

```bash
mobius --help
```

```bash
export MOBIUS_HOME="$(mktemp -d)"
cat > /tmp/mobius-fixture.yaml <<'YAML'
project_type: greenfield
goal: Ship a tiny CLI workflow smoke test.
constraints:
  - Keep all state in the temporary MOBIUS_HOME.
  - Avoid network services.
success:
  - Interview writes a spec.
  - Seed creates a session.
  - Run completes successfully.
YAML
mobius interview --non-interactive --input /tmp/mobius-fixture.yaml --output /tmp/mobius-spec.yaml
mobius seed /tmp/mobius-spec.yaml --json
run_id="$(mobius run --spec /tmp/mobius-spec.yaml)"
mobius status "$run_id" --follow
```

The fastest way to start a real workspace is `mobius init`, which writes a
starter `spec.yaml` and initializes the Mobius event store:

```bash
mkdir my-project && cd my-project
mobius init
# edit spec.yaml, then:
mobius run --spec spec.yaml
mobius status
```

## Command map

Common workflows:

- `mobius init [PATH] [--template web|cli|lib|etl|mobile|docs|blank]` —
  scaffold a workspace with a starter `spec.yaml`. Without `--template`,
  Mobius auto-detects the project type from the cwd
  (`package.json`→web, `Cargo.toml`→cli, `pyproject.toml`→lib,
  `mkdocs.yml`→docs, `pubspec.yaml`→mobile, else `blank`).
- `mobius interview` (interactive prompt-based, auto-detects template) or
  `mobius interview --non-interactive --input fixture.yaml`
- `mobius seed spec.yaml --json`
- `mobius run --spec spec.yaml` (detached by default)
- `mobius runs ls` — list runs in the event store
- `mobius status <run_id> --follow`
- `mobius qa <run_id> --offline --json`
- `mobius evolve --from <run_id> --generations 3`
- `mobius setup --runtime claude --dry-run`

See [`docs/cli-reference.md`](docs/cli-reference.md) for every command, flag,
and exit code, and [`docs/project-types.md`](docs/project-types.md) for
worked examples per project type (web, CLI, library, ETL, mobile, docs).

### Spec model

`spec.yaml` accepts the following top-level keys (all optional except `goal`,
`constraints`, `success_criteria`):

| Key | Purpose |
| --- | --- |
| `project_type` | `greenfield` (new) or `brownfield` (existing). |
| `goal` | One-line statement of what the project ships. **Required.** |
| `constraints` | List of invariants the work must respect. **Required.** |
| `success_criteria` (or `success`) | List of testable outcomes. **Required.** |
| `context` | Free-text description of the existing system (brownfield only). |
| `steps` | Ordered list of named work items, each with optional `command` and `depends_on`. Mobius does **not** execute `command`; it is recorded as metadata for agents/CI. |
| `matrix` | Mapping of axis name → list of values, e.g. `platform: [ios, android]`. |
| `metadata` | Free-form key/value descriptive metadata. |
| `template` | Template name used to scaffold the spec. |

Unknown keys are rejected with a clear `unknown spec key 'X'. Allowed
top-level keys: …` message — no more cryptic YAML diagnostics.

## Development

```bash
uv sync --all-groups
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy --strict src/mobius/
```
