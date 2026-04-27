---
name: ac-tree
description: Print a compact acceptance-criteria tree for a Mobius run.
---

# AC Tree

## When to use

Use to render the acceptance-criteria hierarchy for a run.

## How to invoke

```text
Bash('mobius ac-tree <run_id>')
Bash('mobius ac-tree <run_id> --json')
Bash('mobius ac-tree <run_id> --max-nodes 100 --cursor 0')
```

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
