---
name: cancel
description: Cancel a Mobius run or evolution session by session id.
---

# Cancel

## When to use

Use when the user wants to stop a detached or foreground Mobius session.

## How to invoke

Run `mobius cancel <session-id>` via the Bash tool. For example:

```text
Bash('mobius cancel <session-id>')
```

Preserve any user-provided arguments and pass them to `mobius cancel` using normal shell quoting.
