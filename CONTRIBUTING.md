# Contributing to Mobius

Thanks for your interest in Mobius! This is a small, focused CLI: every change
must keep the non-negotiable invariants intact. Read [`AGENTS.md`](AGENTS.md)
and [`docs/architecture.md`](docs/architecture.md) before starting.

## Non-negotiable invariants

These are enforced by tests and CI and must not be relaxed without an explicit
release note:

- **Zero MCP**: no `mcp` runtime dependency, no `import mcp` in
  `src/mobius/`, and `mobius setup` never registers an MCP server.
- **Stdout discipline**: only command data on stdout. Logs go to stderr.
- **SQLite always WAL**: every connection opens with `journal_mode=WAL`,
  `busy_timeout=30000`, `synchronous=NORMAL`, `foreign_keys=ON`.
- **Detach by default**: `mobius run` and `mobius evolve` return a session id
  within ~1 second and run the actual work in a subprocess.
- **Cold-start budgets**: `mobius --help` p95 ≤ 90 ms and `mobius status`
  p95 ≤ 130 ms on the CI runner. See [`docs/benchmarks.md`](docs/benchmarks.md)
  for methodology.

## Getting started

```bash
git clone https://github.com/charlescstpierr/mobius-cli
cd mobius-cli
uv sync --all-groups
```

## Running tests

```bash
uv run pytest -q                          # full suite (unit + e2e + chaos)
uv run pytest tests/unit -q               # unit only
uv run pytest tests/chaos -q              # chaos only
uv run pytest --cov=src/mobius \
              --cov-report=term-missing \
              --cov-branch                # with coverage
```

The coverage gate requires **≥ 95% line** and **≥ 90% branch**. CI fails below
that threshold.

## Lint and types

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy --strict src/mobius/
```

`ruff format --check` must succeed; run `uv run ruff format src/ tests/`
locally before opening a pull request.

## Building

```bash
uv build              # produces dist/mobius-<version>-py3-none-any.whl
                      # and dist/mobius-<version>.tar.gz
```

The resulting wheel must contain no `Requires-Dist: mcp*` entry; the release
test suite asserts this from a fresh venv.

## Branch naming

Use a short, kebab-case prefix that matches the conventional commit type of
the dominant change:

| Prefix         | Use for                                                       |
|----------------|---------------------------------------------------------------|
| `feat/...`     | User-visible new functionality.                               |
| `fix/...`      | Bug fixes.                                                    |
| `perf/...`     | Performance improvements without behavior change.             |
| `refactor/...` | Internal restructuring with no public surface change.         |
| `docs/...`     | Documentation-only changes (this branch is a `docs/...` one). |
| `test/...`     | Test-only additions or fixes.                                 |
| `chore/...`    | Tooling, build, or release plumbing.                          |
| `ci/...`       | CI configuration only.                                        |

## Commit hygiene

- **One logical change per commit.** Do not mix performance work with feature
  work or with refactors. If you discover this happened (as it did once for
  `v0.1.1`), document the split in the next `CHANGELOG.md` entry rather than
  rewriting published history.
- Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes:
  `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `chore`, `ci`,
  `build`, `revert`.
- Keep the subject line ≤ 72 characters and the body wrapped at 80.
- Every commit message ends with the co-author trailer:

  ```text
  Co-authored-by: factory-droid[bot] <138933559+factory-droid[bot]@users.noreply.github.com>
  ```

## Pull requests

- Add or update tests for every behavior change.
- Keep cold-start tests green; if you must regress a budget, document the
  trade-off in [`docs/benchmarks.md`](docs/benchmarks.md) and call it out
  explicitly in the PR description.
- Update `CHANGELOG.md` under the `[Unreleased]` section.

## Reporting issues

Use [GitHub Issues](https://github.com/charlescstpierr/mobius-cli/issues) for
bugs and feature ideas. For security issues, see [`SECURITY.md`](SECURITY.md).
