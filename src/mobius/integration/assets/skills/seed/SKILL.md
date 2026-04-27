---
name: seed
description: Validate a spec.yaml and persist a seed session in the Mobius event store.
---

# Seed

## When to use

Use after the `interview` skill has produced a `spec.yaml` (or the user
hand-edited one) and you want Mobius to validate it and create a seed
session before a run.

## How to invoke

```text
Bash('mobius seed spec.yaml')
Bash('mobius seed spec.yaml --json')
```

Validation errors exit with code 3 and print the offending key on stderr.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
- Pass user-supplied flags through verbatim using shell quoting.
