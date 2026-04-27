# Security Policy

## Reporting a vulnerability

If you discover a security issue in Mobius, please **do not** open a public
GitHub issue, discussion, or pull request. Instead, use GitHub's private
vulnerability reporting:

1. Go to the
   [Security Advisories tab](https://github.com/charlescstpierr/mobius-cli/security/advisories/new)
   on the Mobius repository.
2. Click **Report a vulnerability** and fill in the private form.

You can also reach out by opening a private security advisory directly from
the repository's **Security** tab.

## Response SLA

- **Acknowledgement:** within **3 business days** of receipt.
- **Initial assessment** (severity, scope, reproducibility): within
  **7 business days**.
- **Fix or coordinated mitigation plan**: target within **30 days** for
  high-severity issues; longer windows are negotiated case-by-case for
  lower-severity reports.

We will keep you informed throughout the process and credit you in the
release notes unless you request otherwise.

## Supported versions

Only the latest minor release line receives security fixes. Older releases
should be upgraded to a supported version.

| Version  | Supported          |
|----------|--------------------|
| `0.1.x`  | ✅ Supported       |
| `< 0.1`  | ❌ Not supported   |

## Scope

In scope:

- The `mobius` CLI (anything under `src/mobius/`).
- The published wheels and source distributions on GitHub Releases.
- Files installed by `mobius setup` (`skills/`, `.claude/commands/`,
  `hooks/`).

Out of scope:

- Vulnerabilities in upstream dependencies (`typer`, `pydantic`, `rich`).
  Please report those to their respective maintainers.
- Vulnerabilities in `Q00/ouroboros` (the upstream project this CLI is
  inspired by but does not reuse).

## Security invariants we rely on

These are documented for transparency. If you believe any of them are
violated, that is a security issue worth reporting:

- The Mobius event store is a single-user SQLite database under
  `~/.mobius/events.db` with file mode `0600` and parent directory `0700`.
- `mobius setup` never writes any MCP server registration to any agent
  runtime configuration.
- The CLI never executes user-supplied code from spec files; specs are
  pure data.
- The CLI never makes outbound network calls in `--offline` mode.
