---
name: seed
description: Generate a Mobius seed from an interview session or spec input.
---

# Seed

## When to use

Use when the user wants to create an executable seed before running work.

## How to invoke

Run `mobius seed <spec-file>` via the Bash tool. For example:

```text
Bash('mobius seed <spec-file>')
```

Preserve any user-provided arguments and pass them to `mobius seed` using normal shell quoting.
