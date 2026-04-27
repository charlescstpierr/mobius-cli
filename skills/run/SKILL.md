---
name: run
description: Execute a Mobius seed or specification as a managed session.
---

# Run

## When to use

Use when the user is ready to run Mobius work from a seed or spec file.

## How to invoke

Run `mobius run --spec <spec-file>` via the Bash tool. For example:

```text
Bash('mobius run --spec <spec-file>')
```

Preserve any user-provided arguments and pass them to `mobius run` using normal shell quoting.
