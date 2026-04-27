---
name: evolve
description: Run the Mobius evolutionary improvement loop from a prior session.
---

# Evolve

## When to use

Use when the user asks to refine or improve results from an existing run or seed.

## How to invoke

Run `mobius evolve --from <session-id>` via the Bash tool. For example:

```text
Bash('mobius evolve --from <session-id>')
```

Preserve any user-provided arguments and pass them to `mobius evolve` using normal shell quoting.
