# Agent integration — Claude Code, Codex, Hermes

Mobius is a plain CLI. **It does not call any LLM.** Your coding agent
holds the conversation with the user; once the agent has the goal,
constraints, and success criteria, it invokes
`mobius interview --non-interactive` via the `Bash` tool. Mobius records
the spec, emits events, and tracks state.

The flow is identical across runtimes:

```
┌──────────────┐  conversation  ┌────────┐   Bash('mobius interview …')   ┌────────┐
│ user / human │ ─────────────▶ │ agent  │ ───────────────────────────▶ │ mobius │
└──────────────┘ ◀───────────── └────────┘ ◀── stdout: spec.yaml + ───── └────────┘
                  spec.yaml                       session_id
```

> **Never** invoke Mobius via MCP. Mobius has no MCP runtime and
> `mobius setup` never registers one. Always use the agent's `Bash` tool.

## One-time setup

Pick the runtime you use, then run:

```bash
mobius setup --runtime claude     # Claude Code
mobius setup --runtime codex      # OpenAI Codex CLI / Codex desktop
mobius setup --runtime hermes     # Hermes
```

Add `--scope project` to install under the current workspace's
`./.<runtime>/...` instead of `~/.<runtime>/...`. Add `--dry-run` to
preview. The command is idempotent — re-run it after a Mobius upgrade.

### What gets installed where

| Runtime | Skills (long-form) | Slash commands / prompts |
| ------- | ------------------ | ------------------------- |
| `claude` | `~/.claude/skills/<name>/SKILL.md` | `~/.claude/commands/<name>.md` |
| `codex`  | `~/.codex/skills/<name>/SKILL.md`  | `~/.codex/prompts/<name>.md` |
| `hermes` | `~/.hermes/skills/<name>/SKILL.md` | `~/.hermes/commands/<name>.md` |

Each install ships eleven skills and eleven matching commands/prompts:
`interview`, `seed`, `run`, `status`, `runs ls` (via `help`), `cancel`,
`qa`, `evolve`, `lineage`, `ac-tree`, `setup`, `help`. See
[`docs/cli-reference.md`](cli-reference.md) for the full CLI surface.

### What's in each asset

Every skill explains, for the agent:

1. **Mobius exists** and what it tracks.
2. **When** to use the skill (concrete user triggers).
3. **How** to invoke it — exact `Bash('mobius …')` calls with realistic
   flags and a worked example.
4. **What NOT to do** — never call MCP; do not invent fixtures unless
   asked; pass each constraint/success-criterion as its own flag.

## What the user types

Once setup is done, the user can simply say things like:

- "Help me set up this project."
- "I want to build a Next.js sales dashboard with auth."
- "/interview" (slash command).

The agent's `interview` skill kicks in, holds the conversation, scans the
workspace (e.g. reads `package.json`), summarises back to the user, and
then composes the CLI invocation.

## Worked example — Claude Code, Codex, or Hermes

User says:

> *"I want to build a Next.js dashboard for tracking sales, with auth,
> deploys to Vercel. Must hit Lighthouse 90+."*

The agent reads `package.json` (finds `next`), asks one follow-up about
the auth provider, then calls:

```bash
mobius interview --non-interactive \
  --template web \
  --project-type greenfield \
  --goal "Ship a Next.js sales dashboard with auth deployed to Vercel" \
  --constraint "Deploy target is Vercel" \
  --constraint "Use NextAuth.js for authentication" \
  --success-criterion "Lighthouse score >= 90 on the dashboard route" \
  --success-criterion "Auth flow works end-to-end" \
  --success-criterion "Vercel preview deploy succeeds" \
  --output spec.yaml
```

Mobius writes `spec.yaml`, prints `session_id=interview_abcd…` on stdout,
and records every question/answer as events. The agent then offers:

```bash
mobius seed spec.yaml --json
mobius run --spec spec.yaml          # detached by default; prints run_id
mobius status <run_id> --follow      # streams progress
mobius qa <run_id>                   # offline QA judge
```

## Brownfield variant

Add `--project-type brownfield` and `--context "<existing-system>"` so
the spec records what must be preserved:

```bash
mobius interview --non-interactive \
  --template lib \
  --project-type brownfield \
  --goal "Migrate the library to a v2 API without breaking consumers" \
  --constraint "Public API must remain backwards compatible" \
  --success-criterion "All existing consumers continue to work" \
  --context "Library has 3 years of consumers; semver is strict." \
  --output spec.yaml
```

## Agent flag reference

| Flag | Repeatable | Purpose |
| ---- | ---------- | ------- |
| `--non-interactive` | — | Required when not driving prompts on stdin. |
| `--template` | — | One of `web`, `cli`, `lib`, `etl`, `mobile`, `docs`, `blank`. |
| `--project-type` | — | `greenfield` (default) or `brownfield`. |
| `--goal` | no | One-sentence goal. Required if no `--input` fixture is given. |
| `--constraint` | **yes** | Pass once per constraint. |
| `--success-criterion` | **yes** | Pass once per criterion. |
| `--context` | no | Brownfield context. Ignored unless `--project-type=brownfield`. |
| `--input` | no | Optional fixture file. CLI flags override fixture values when both are present. |
| `--output` | no | Spec destination. Defaults to `./spec.yaml`. |

## Verifying the install

After `mobius setup --runtime <name>`, the agent should be able to:

1. List the new skills/commands (Claude Code surfaces them under
   `/help`; Codex shows prompts via `/`).
2. Read `~/.<runtime>/skills/interview/SKILL.md` and find the
   `Bash('mobius interview --non-interactive …')` invocation pattern.
3. Run `mobius --help` via `Bash` to confirm the binary is on PATH.

If something is missing, re-run `mobius setup --runtime <name>` (it is
idempotent) or pass `--scope project` to install under the current
workspace.
