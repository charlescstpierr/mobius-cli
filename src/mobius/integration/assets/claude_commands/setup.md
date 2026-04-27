---
description: Install or remove Mobius integration assets in this runtime.
---

# /setup

Use the `Bash` tool — **never** MCP. Mobius has no MCP server and never
registers one in agent config.

```text
Bash('mobius setup --runtime claude --dry-run')
Bash('mobius setup --runtime claude')
Bash('mobius setup --runtime codex')
Bash('mobius setup --runtime hermes')
Bash('mobius setup --runtime claude --uninstall')
Bash('mobius setup --runtime claude --scope project')
```

Setup is idempotent.
