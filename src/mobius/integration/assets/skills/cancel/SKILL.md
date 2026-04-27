---
name: cancel
description: Cancel a detached Mobius run by run id.
---

# Cancel

## When to use

Use when the user wants to stop a detached run created by `mobius run`.

## How to invoke

```text
Bash('mobius cancel <run_id>')
Bash('mobius cancel <run_id> --grace-period 5')
```

The worker handles SIGTERM idempotently; a `<runtime>.cancelled` event is
written exactly once.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
