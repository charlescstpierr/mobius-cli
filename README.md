# Mobius

[![CI](https://github.com/charlescstpierr/mobius-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/charlescstpierr/mobius-cli/actions/workflows/ci.yml)

Repository: <https://github.com/charlescstpierr/mobius-cli>

Mobius is a from-scratch Python CLI rewrite inspired by
[Q00/ouroboros](https://github.com/Q00/ouroboros). It keeps the interview,
seed, execution, QA, and evolution workflow ideas, but exposes them as fast
one-shot shell commands instead of a long-running MCP server.

## Install

Install the published CLI directly from the GitHub repository with either
[`uv`](https://docs.astral.sh/uv/) or [`pipx`](https://pipx.pypa.io/):

- `uv tool install git+https://github.com/charlescstpierr/mobius-cli`
- `pipx install git+https://github.com/charlescstpierr/mobius-cli`

## Quickstart

Run these first three blocks from the repository root. They install the
`mobius` command and exercise the CLI end-to-end in an isolated state directory.

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

## Command map

Common workflows:

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
