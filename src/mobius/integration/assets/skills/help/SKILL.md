---
name: help
description: Show Mobius CLI help and explain what Mobius does and how to drive it.
---

# Help

## What Mobius is

Mobius is a **fast, MCP-free workflow CLI** that records project specs,
runs, and acceptance-criteria as events in a SQLite store. It is **not**
an LLM, a build runner, or an MCP server.

You — the coding agent — drive it with the `Bash` tool.

## When to use

Use when the user asks "what can Mobius do" or wants to discover commands.

## How to invoke

```text
Bash('mobius --help')        # equivalent to `mobius help`
Bash('mobius <subcommand> --help')
```

## Common subcommands the agent will dispatch

| Goal | Skill / Command |
| ---- | --------------- |
| Hold an interview and produce a spec | `interview` skill / `mobius interview --non-interactive --goal ...` |
| Scaffold a workspace | `mobius init [--template ...]` |
| Validate a spec into a seed session | `mobius seed spec.yaml` |
| Execute a run | `mobius run --spec spec.yaml` |
| Inspect status / progress | `mobius status [<run_id>] [--follow]` |
| List runs | `mobius runs ls [--all]` |
| Cancel a detached run | `mobius cancel <run_id>` |
| QA a completed run | `mobius qa <run_id>` |
| Evolve from a prior run | `mobius evolve --from <run_id>` |
| Inspect lineage | `mobius lineage <aggregate_id>` |
| Render the AC tree | `mobius ac-tree <run_id>` |
| Install assets in this runtime | `mobius setup --runtime <claude|codex|hermes>` |

## Rules of engagement

- Always invoke Mobius via `Bash('mobius ...')`. **Never** via MCP — Mobius
  has no MCP server.
- `mobius --help` is cold-start budgeted (< 150 ms) — call it freely to
  discover flags before constructing complex invocations.
- Stdout is data; stderr is logs. Pipe the stdout when scripting.
