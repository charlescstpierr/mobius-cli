---
description: Start a Mobius run for a validated spec.
---

# /run

Use the `Bash` tool — **never** MCP. Mobius has no MCP server. Mobius
records events; it does not execute the spec's `steps` itself.

```text
Bash('mobius run --spec spec.yaml')                # detached
Bash('mobius run --spec spec.yaml --foreground')   # streams to stderr
```

Stdout is the run id.
