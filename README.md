# Mobius

Mobius is a from-scratch Python CLI rewrite inspired by
[Q00/ouroboros](https://github.com/Q00/ouroboros), designed as a fast,
one-shot command-line tool with no MCP server dependency.

## Status

This repository is being bootstrapped. The initial package layout and
`mobius` console entry point are present; command implementations will be
added in later milestones.

## Development

```bash
uv sync --all-groups
uv run pytest -q
uv run mobius
```
