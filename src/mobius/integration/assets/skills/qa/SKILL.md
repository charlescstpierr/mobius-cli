---
name: qa
description: Run the Mobius QA judge for a completed session.
---

# QA

## When to use

Use when the user wants to verify a Mobius run against its acceptance criteria.

## How to invoke

Run `mobius qa <session-id>` via the Bash tool. For example:

```text
Bash('mobius qa <session-id>')
```

Preserve any user-provided arguments and pass them to `mobius qa` using normal shell quoting.
