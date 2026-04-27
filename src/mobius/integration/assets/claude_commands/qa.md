---
description: Run the offline Mobius QA judge for a completed run.
---

# /qa

Use the `Bash` tool — **never** MCP. Mobius has no MCP server. The QA
judge is offline-first; no LLM call is made.

```text
Bash('mobius qa <run_id>')
Bash('mobius qa <run_id> --json')
```
