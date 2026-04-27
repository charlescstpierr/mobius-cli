---
description: Run the Mobius evolution loop from a prior run.
---

# /evolve

Use the `Bash` tool — **never** MCP. Mobius has no MCP server.

```text
Bash('mobius evolve --from <run_id>')
Bash('mobius evolve --from <run_id> --generations 3')
Bash('mobius evolve --from <run_id> --foreground')
```

Detached by default. Hard-capped at 30 generations.
