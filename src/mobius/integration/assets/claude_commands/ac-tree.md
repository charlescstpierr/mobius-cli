---
description: Print a compact acceptance-criteria tree for a Mobius run.
---

# /ac-tree

Use the `Bash` tool — **never** MCP. Mobius has no MCP server.

```text
Bash('mobius ac-tree <run_id>')
Bash('mobius ac-tree <run_id> --json')
Bash('mobius ac-tree <run_id> --max-nodes 100 --cursor 0')
```
