# Changelog

All notable changes to Mobius are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Placeholder for the next release. Add user-visible changes here as pull
  requests land.

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

[Unreleased]: https://github.com/charlescstpierr/mobius-cli/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.1
[0.1.0]: https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.0
