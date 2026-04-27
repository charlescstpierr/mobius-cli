---
name: run
description: Start a detached Mobius run for a validated spec.
---

# Run

## When to use

Use when the user is ready to execute work tracked by a `spec.yaml`. Mobius
records events; it does **not** itself execute the user's `steps` or
`matrix` — those are descriptive metadata. Bring your own runner (Make,
npm, cargo, dbt, your CI) and call it alongside `mobius run`.

## How to invoke

```text
Bash('mobius run --spec spec.yaml')                 # detached (default)
Bash('mobius run --spec spec.yaml --foreground')    # streams events to stderr
```

Stdout is the run id. Use it for `mobius status <run_id> --follow`.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
- Pass user-supplied flags through verbatim using shell quoting.
