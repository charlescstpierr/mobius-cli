---
name: interview
description: Drive the user through a project-discovery conversation, then record the resulting spec via `mobius interview --non-interactive`.
---

# Interview

Mobius does not call any LLM. **You** (the agent) hold the conversation; once
you have enough information, you invoke `mobius interview` via the **Bash
tool** with extracted parameters. Mobius records the spec and emits events.

> **Never** invoke Mobius via MCP. Mobius has no MCP server. Always use the
> `Bash` tool with the `mobius` shell command.

## When to use

Use whenever the user wants to start a new project (greenfield) or describe
an existing one (brownfield) for tracking. Typical triggers:

- "Help me set up this project."
- "I want to build X."
- "Use Mobius to track this work."
- "/interview" (slash command).

Do **not** use this skill to merely list `mobius` commands; use the `help`
skill for that.

## Step-by-step

### 1. Read the workspace

Before talking, scan the cwd to detect the project type. Mobius will
auto-detect with `detect_template`, but knowing the type up front lets you
ask better follow-ups.

| File found | Likely template |
| ---------- | --------------- |
| `package.json` | `web` |
| `Cargo.toml` | `cli` |
| `pyproject.toml` | `lib` |
| `pubspec.yaml` or `ios/`+`android/` | `mobile` |
| `mkdocs.yml` or `docs/index.md` | `docs` |
| `dbt_project.yml` or `airflow.cfg` | `etl` |
| nothing recognisable | `blank` (greenfield) |

If a manifest exists, read it (`Read package.json`, `Read Cargo.toml`, etc.)
to learn the project name, scripts, and existing dependencies. Reference
them in your follow-up questions instead of asking the user from scratch.

### 2. Hold the conversation

Ask, in your own words and at your own pace, until you have:

1. **Goal** — one sentence describing what the project should ship.
2. **Constraints** — invariants the work must respect (perf, deps, deploy
   target, regulatory, "no breaking changes", etc.).
3. **Success criteria** — testable outcomes. Push for measurable ones
   (Lighthouse ≥ 90, coverage ≥ 95%, p95 < 200ms…).
4. **Project type** — `greenfield` (new) or `brownfield` (existing).
5. **(Brownfield only) context** — what existing system must be preserved.

Keep it conversational. Do not interrogate. Summarise back to the user
before moving to step 3.

### 3. Extract → invoke `mobius interview`

Once the user confirms, call:

```text
Bash('mobius interview --non-interactive \
  --template <web|cli|lib|etl|mobile|docs|blank> \
  --project-type <greenfield|brownfield> \
  --goal "<one sentence>" \
  --constraint "<constraint 1>" \
  --constraint "<constraint 2>" \
  --success-criterion "<criterion 1>" \
  --success-criterion "<criterion 2>" \
  [--context "<existing-system context>"] \
  --output spec.yaml')
```

Pass each constraint and each success criterion as its **own**
`--constraint` / `--success-criterion` flag. Quote values that contain
spaces. Mobius writes `spec.yaml` and a session id to stdout.

### 4. Hand back, then drive `mobius init` / `seed` / `run`

Show the user the path to `spec.yaml`, then offer the next action:

```text
Bash('mobius init')          # scaffolds a workspace if needed
Bash('mobius seed spec.yaml')
Bash('mobius run --spec spec.yaml')
Bash('mobius status <run_id> --follow')
```

## Worked example

User: *"I want to build a Next.js dashboard for tracking sales, with auth.
Deploys to Vercel. Must hit Lighthouse 90+."*

You inspect the cwd, find a `package.json` with `"next"`, ask one
follow-up ("Any auth provider preference?"), then call:

```text
Bash('mobius interview --non-interactive \
  --template web \
  --project-type greenfield \
  --goal "Ship a Next.js sales dashboard with auth deployed to Vercel" \
  --constraint "Deploy target is Vercel" \
  --constraint "Use NextAuth.js for authentication" \
  --success-criterion "Lighthouse score >= 90 on the dashboard route" \
  --success-criterion "Auth flow works end-to-end" \
  --success-criterion "Vercel preview deploy succeeds" \
  --output spec.yaml')
```

## What NOT to do

- Do **not** call any MCP tool. Mobius is a plain CLI.
- Do **not** pass a flat `--constraint "a, b, c"` — repeat the flag.
- Do **not** invent a fixture YAML file unless the user explicitly asks for
  one — `--goal/--constraint/--success-criterion` is the default agent path.
- Do **not** skip the conversation and go straight to invoking the CLI; the
  whole point is that you elicit the spec from the user.
