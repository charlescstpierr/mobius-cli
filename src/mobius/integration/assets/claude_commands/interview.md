---
description: Drive a Mobius project interview conversationally and record the spec.
---

# /interview

Mobius does **not** call an LLM. **You** (the agent) hold the conversation
with the user, then invoke `mobius interview --non-interactive` via the
`Bash` tool with extracted parameters. **Never** invoke Mobius via MCP.

## What to do

1. **Read the workspace** with `Read` / `LS` to detect the project type
   (`package.json`→web, `Cargo.toml`→cli, `pyproject.toml`→lib,
   `pubspec.yaml`→mobile, `mkdocs.yml`→docs, `dbt_project.yml`→etl).
2. **Ask the user** for: goal (one sentence), constraints, success
   criteria, project type (greenfield/brownfield), and — if brownfield —
   existing-system context.
3. **Summarise back** to the user; wait for confirmation.
4. **Invoke**:

   ```text
   Bash('mobius interview --non-interactive \
     --template <web|cli|lib|etl|mobile|docs|blank> \
     --project-type <greenfield|brownfield> \
     --goal "<one sentence>" \
     --constraint "<c1>" \
     --constraint "<c2>" \
     --success-criterion "<s1>" \
     --success-criterion "<s2>" \
     [--context "<existing>"] \
     --output spec.yaml')
   ```

   Repeat `--constraint` and `--success-criterion` once per item.

5. **Hand back** the resulting `spec.yaml` to the user, then offer:

   ```text
   Bash('mobius seed spec.yaml')
   Bash('mobius run --spec spec.yaml')
   Bash('mobius status <run_id> --follow')
   ```

Pass any extra user-supplied flags through verbatim with normal shell
quoting.
