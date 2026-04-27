---
name: evolve
description: Run the Mobius generation evolution loop from a prior run.
---

# Evolve

## When to use

Use to refine results across generations starting from a completed run id.

## How to invoke

```text
Bash('mobius evolve --from <run_id>')
Bash('mobius evolve --from <run_id> --generations 3')
Bash('mobius evolve --from <run_id> --foreground')
```

Detached by default. Hard-capped at 30 generations.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
