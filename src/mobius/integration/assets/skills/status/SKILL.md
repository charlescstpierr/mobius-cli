---
name: status
description: Inspect Mobius session status or follow live progress.
---

# Status

## When to use

Use when the user asks for the current state of a run or evolution session.

## How to invoke

Run `mobius status <session-id>` via the Bash tool. For example:

```text
Bash('mobius status <session-id>')
```

Preserve any user-provided arguments and pass them to `mobius status` using normal shell quoting.
