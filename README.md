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

- `mobius init [PATH]` — scaffold a workspace with a starter `spec.yaml`
- `mobius interview --non-interactive --input fixture.yaml --output spec.yaml`
- `mobius seed spec.yaml --json`
- `mobius run --spec spec.yaml` (detached by default)
- `mobius status <run_id> --follow`
- `mobius qa <run_id> --offline --json`
- `mobius evolve --from <run_id> --generations 3`
- `mobius setup --runtime claude --dry-run`

See [`docs/cli-reference.md`](docs/cli-reference.md) for every command, flag,
and exit code.

## Development

```bash
uv sync --all-groups
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy --strict src/mobius/
```
