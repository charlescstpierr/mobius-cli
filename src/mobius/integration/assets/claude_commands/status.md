---
description: Show Mobius event-store status, optionally for a specific run id.
---

# /status

Use the `Bash` tool — **never** MCP. Mobius has no MCP server.

```text
Bash('mobius status')                       # global summary
Bash('mobius status <run_id>')
Bash('mobius status <run_id> --follow')
Bash('mobius status <run_id> --json')
```
