---
name: lineage
description: Render lineage (ancestors / descendants / replay hash) for a Mobius aggregate.
---

# Lineage

## When to use

Use to inspect how a run/evolution descends from earlier sessions, or to
get the deterministic SHA-256 replay hash.

## How to invoke

```text
Bash('mobius lineage <aggregate_id>')
Bash('mobius lineage <aggregate_id> --json')
Bash('mobius lineage <aggregate_id> --hash')
```

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
