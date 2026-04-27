---
description: Validate a spec.yaml and create a Mobius seed session.
---

# /seed

Use the `Bash` tool — **never** MCP. Mobius has no MCP server.

```text
Bash('mobius seed spec.yaml')
Bash('mobius seed spec.yaml --json')
```

Validation errors exit with code 3.
