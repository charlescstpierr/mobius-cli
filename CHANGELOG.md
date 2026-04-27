# Changelog

All notable changes to Mobius are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-04-27

### Fixed

- **Friendly error on bad `MOBIUS_HOME`**: a read-only or non-existent path
  no longer surfaces a Python traceback. The CLI now prints a single-line
  `cannot create Mobius state directory at <path>: <reason>` to stderr and
  exits with code 1. (`fix(cli)`)
- **`mobius config get` parity with `config show`**: derived paths
  (`event_store`, `state_dir`, `config_file`) are now resolvable through
  `config get`, matching what `config show` lists. (`fix(config)`)
- **`mobius interview --non-interactive` exit codes**: missing `--input` /
  `--output` already exited with code 2; pinned by regression tests so it
  cannot regress. (`test(interview)`)

### Changed

- **`mobius setup` ships its assets inside the wheel.** Skill manifests and
  Claude slash commands are now packaged under `mobius/integration/assets/`
  and resolved via `importlib.resources`, so a `pip install <wheel-url>`
  install installs the same content as a `uv tool install` source build.
  The summary line now reports `installed N (M written, K unchanged)`. The
  zero-asset fallback message points at the GitHub releases page. The
  source-tree `skills/` and `.claude/commands/` directories are now
  symlinks into the package data, eliminating duplication. (`feat(setup)`)
- `output.write_line` uses `soft_wrap=True` so long file paths do not get
  hard-wrapped on narrow terminals or non-tty pipes. (`fix(output)`)
- `mobius.cli.entry_point` is exposed as a stable reference to the
  package-level `main()` function, immune to submodule shadowing.

### Documentation

- README lists `pip install <wheel-url>` as the first install option.
- README has a new "State directory" section explaining `MOBIUS_HOME`,
  the `~/.mobius/events.db` default, and how to make event stores
  per-project.
- `mobius init` now prints the resolved `mobius_home` and a comment
  explaining whether `MOBIUS_HOME` came from the environment or the
  default, plus a one-line tip showing how to opt into per-project state.

## [0.1.2] - 2026-04-27

### Added

- **Test coverage to 95.99%** (line) with branch coverage enabled. +221
  tests across CLI handlers, workflow branches, and persistence edges.
- **Chaos coverage**: SIGKILL fsync, disk-full, race-condition, and
  failing-migration scenarios under `tests/chaos/`.
- **Property-based testing**: Hypothesis test verifying replay
  determinism over arbitrary event orderings.
- **Cold-start regression guard** (`.github/workflows/perf-guard.yml` +
  `bench/ci_perf_guard.py`): hard CI budgets on `mobius --help` and
  `mobius status` p95 enforced on every push.
- `CONTRIBUTING.md`, `SECURITY.md`, README status badges, and a
  refreshed migration guide from upstream `Q00/ouroboros`.
- `docs/benchmarks.md`: methodology, dev-box vs CI budget rationale, and
  hyperfine recipes.

### Changed

- Coverage gate raised from 80% → 95% (line) with branch coverage on by
  default in `pyproject.toml`.

## [0.1.1] - 2026-04-27

### Added

- `mobius init [PATH]` — scaffold a workspace with a starter `spec.yaml` and
  initialize the Mobius event store inline. (`feat(init)`)

### Performance

- `mobius status` cold path on a fresh `MOBIUS_HOME`: p50 dropped from
  ~430 ms to ~74 ms; p95 from ~493 ms to ~109 ms (hyperfine, n=30).
- `mobius status` warm path: p50 dropped from ~357 ms to ~65 ms; p95 from
  ~376 ms to ~76 ms.
- `mobius --help` and `mobius --version` cold paths now skip
  Typer/Rich/Pydantic imports and stay under ~80 ms p95.
- Implementation: deferred Typer/Rich/Pydantic imports until a real workflow
  command is dispatched, plus a migration-version cache for `mobius status`.
  (`perf(status)`)

### Notes

- **Released as a single commit** (`0e27bd0`). The `v0.1.1` tag bundles two
  logically independent changes — `perf(status): cold-start p95 from 343ms
  to <116ms via lazy imports + migration cache` and `feat(init): add mobius
  init workspace scaffold` — into one commit. They are split into two
  logical changes for clarity in the entries above. History is **not**
  rewritten because the tag has been pulled by collaborators; this entry
  is the forward-only record. Future releases will keep one logical change
  per commit.

## [0.1.0] - 2026-04-26

### Added

- Initial public release.
- Typer-based `mobius` CLI with the full workflow surface: `interview`,
  `seed`, `run`, `status`, `ac-tree`, `qa`, `cancel`, `evolve`, `lineage`,
  `setup`, and `config`.
- Event-sourced SQLite store (always WAL, `busy_timeout=30000`,
  `synchronous=NORMAL`, `foreign_keys=ON`), idempotent migrations, and a
  deterministic replay hash.
- Detach-by-default `run` and `evolve`; `--foreground` opt-in; SIGTERM
  graceful cancel and SIGINT exit-130 paths.
- Stdout discipline: only command data on stdout; logs always on stderr.
- Zero MCP runtime deps (verified by tests on the published wheel
  `METADATA`).
- Agent integration assets (`skills/`, `.claude/commands/`, `hooks/`) and
  `mobius setup --runtime {claude,codex,hermes}` for idempotent installs.

[Unreleased]: https://github.com/charlescstpierr/mobius-cli/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.3
[0.1.2]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.2
[0.1.1]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.1
[0.1.0]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.0
