---
description: Cancel a detached Mobius run by run id.
---

# /cancel

Use the `Bash` tool — **never** MCP. Mobius has no MCP server.

```text
Bash('mobius cancel <run_id>')
Bash('mobius cancel <run_id> --grace-period 5')
```

The worker SIGTERM handler is idempotent.
