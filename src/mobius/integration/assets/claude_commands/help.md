---
description: Show Mobius CLI help and explain how the agent should drive it.
---

# /help

Mobius is a fast, MCP-free CLI. Drive it via the `Bash` tool — **never**
via MCP (Mobius has no MCP server).

```text
Bash('mobius --help')        # equivalent to `mobius help`
Bash('mobius <subcommand> --help')
```

Use the `interview` skill / `/interview` command to start a project from
a conversation; use `seed`, `run`, `status`, `runs ls`, `qa`, `cancel`,
`evolve`, `lineage`, `ac-tree`, and `setup` from there.
