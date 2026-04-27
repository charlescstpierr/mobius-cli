---
name: setup
description: Install or remove Mobius agent integration assets in the active runtime.
---

# Setup

## When to use

Use when the user wants to install Mobius into a coding-agent runtime
(Claude Code, Codex, or Hermes).

## How to invoke

```text
Bash('mobius setup --runtime claude --dry-run')   # preview only
Bash('mobius setup --runtime claude')             # install (idempotent)
Bash('mobius setup --runtime codex')              # Codex skills + prompts
Bash('mobius setup --runtime hermes')             # Hermes skills + commands
Bash('mobius setup --runtime claude --uninstall') # clean removal
Bash('mobius setup --runtime claude --scope project')  # ./.claude/...
```

Setup writes:

- `~/.claude/skills/<name>/SKILL.md` + `~/.claude/commands/<name>.md`
- `~/.codex/skills/<name>/SKILL.md` + `~/.codex/prompts/<name>.md`
- `~/.hermes/skills/<name>/SKILL.md` + `~/.hermes/commands/<name>.md`

It **never** registers an MCP server or edits `~/.claude.json` /
`~/.codex/config.toml`. Mobius has no MCP runtime.

## Rules

- Always use the `Bash` tool. Mobius has **no MCP server**.
- Setup is idempotent — repeated runs converge to the same state.
