# Mobius v0.1.4 — Interview UAT

**Date:** 2026-04-27
**Wheel:** `mobius-0.1.4-py3-none-any.whl` (from
[GitHub Release v0.1.4](https://github.com/charlescstpierr/mobius-cli/releases/tag/v0.1.4))
**Verdict:** ✅ All checks pass.

## Setup

```sh
python3 -m venv venv
venv/bin/pip install \
  https://github.com/charlescstpierr/mobius-cli/releases/download/v0.1.4/mobius-0.1.4-py3-none-any.whl
mobius --version  # → mobius 0.1.4
```

## Scenarios exercised

| # | Scenario                                  | Expected                                                                  | Result |
| - | ----------------------------------------- | ------------------------------------------------------------------------- | ------ |
| a | `mobius interview --help`                 | lists `--non-interactive`, `--input`, `--output`, `--template`, `--project-type` | ✅      |
| b | Interactive, EOF stdin in empty cwd       | auto-detects `blank` template, accepts every default, writes `./spec.yaml` | ✅      |
| c | Interactive, full piped answers + `--template web` | writes spec with user-provided goal/constraints/success and `template: web` | ✅      |
| d | `--project-type brownfield --template lib`        | additional context prompt, `context:` populated in spec                      | ✅      |
| e | `--non-interactive --input fixture.json`          | legacy fixture mode unchanged, JSON & YAML inputs accepted                   | ✅      |
| f | Missing `--input` file                            | exit code 2 with typer error and no traceback                                | ✅      |

## Sample interactive transcript

```text
$ mobius interview --template web < /dev/null
# Mobius interview — template: web
# Web app pipeline: lint, typecheck, build, e2e, deploy.
# Press Enter to accept the [default] in brackets.

Project type [greenfield/brownfield]
  [default: greenfield]
> Goal — what should this project ship?
  [default: 'Ship a web app preview deploy with passing lint, typecheck, build, and e2e tests.']
> Constraints (one per line, blank line to finish)
  defaults (Enter on first prompt to accept all):
    - All scripts must exit 0
    - Preview URL must be reachable
> Success criteria (one per line, blank line to finish)
  defaults (Enter on first prompt to accept all):
    - lint passes (npm run lint)
    - typecheck passes (npm run typecheck)
    - build succeeds (npm run build)
    - e2e tests pass (npm run e2e)
    - preview deploy URL emitted
>
# Wrote /tmp/proj/spec.yaml
session_id=interview_7dde5ad64c7c
output=/tmp/proj/spec.yaml
template=web
ambiguity_score=0.0
```

## Generated spec sample (web template)

```yaml
session_id: interview_7dde5ad64c7c
project_type: greenfield
template: web
ambiguity_score: 0.0
ambiguity_gate: 0.2
ambiguity_components:
  goal: 0.0
  constraints: 0.0
  success: 0.0
goal: Ship a web app preview deploy with passing lint, typecheck, build, and e2e tests.
constraints:
  - All scripts must exit 0
  - Preview URL must be reachable
success_criteria:
  - lint passes (npm run lint)
  - typecheck passes (npm run typecheck)
  - build succeeds (npm run build)
  - e2e tests pass (npm run e2e)
  - preview deploy URL emitted
```

## Notes

- All prompts go to **stderr** — stdout stays clean.
- Empty input on a list prompt accepts the template defaults.
- Legacy `--non-interactive` fixture mode (JSON/YAML) is unchanged.
- The `--output` flag defaults to `./spec.yaml`.
