---
name: status
description: Inspect Mobius event-store status, optionally for a specific run id.
---

# Status

## When to use

Use to show overall event-store health, or to follow a specific run.

## How to invoke

```text
Bash('mobius status')                       # global summary
Bash('mobius status <run_id>')              # one run snapshot
Bash('mobius status <run_id> --follow')     # streams deltas every ~200ms
Bash('mobius status <run_id> --json')       # machine-readable
```

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
- p95 cold-start budget is < 300 ms; safe to call repeatedly.
