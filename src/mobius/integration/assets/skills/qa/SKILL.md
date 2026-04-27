---
name: qa
description: Run the offline Mobius QA judge for a completed run.
---

# QA

## When to use

Use after a run completes to evaluate it against its acceptance criteria.

## How to invoke

```text
Bash('mobius qa <run_id>')              # offline by default
Bash('mobius qa <run_id> --json')
```

`--offline` is the default and uses deterministic local heuristics — no LLM
or network call.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server** and no LLM.
