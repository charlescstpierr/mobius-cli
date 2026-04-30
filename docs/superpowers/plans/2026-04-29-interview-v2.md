# Interview v2 — Unified Skill with Quick/Deep Modes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Mobius `/interview` skill to support two modes: deep (default, structured interview with scoring/challenge/pre-mortem) and quick (fast extraction), both producing an enriched `spec.yaml`.

**Architecture:** Add 6 new keys to `ALLOWED_KEYS` in `seed.py` with proper normalization and `SeedSpec` persistence. Extend `render_spec_yaml()` in `interview.py` to accept a `deep_metadata_path` JSON file. Add `--deep-metadata` CLI flag. Rewrite the skill markdown with conditional quick/deep sections.

**Tech Stack:** Python 3.12, Typer, Pydantic, pytest, Mobius CLI

**Spec:** `docs/superpowers/specs/2026-04-29-interview-v2-design.md`

---

### Task 1: Add deep metadata keys to seed.py ALLOWED_KEYS

**Files:**
- Modify: `src/mobius/workflow/seed.py`
- Test: `tests/unit/workflow/test_seed_parsing.py`

- [ ] **Step 1: Write failing test — unknown deep keys are rejected**

Add to `tests/unit/workflow/test_seed_parsing.py`:

```python
def test_validate_seed_spec_accepts_deep_interview_keys() -> None:
    spec = {
        "project_type": "greenfield",
        "goal": "Test deep metadata acceptance",
        "constraints": ["No regressions"],
        "success_criteria": ["Deep keys pass validation"],
        "interview_mode": "deep",
        "clarity_score": {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"},
        "assumptions": [{"statement": "Gate won't block", "status": "validated"}],
        "premortem": "Failure if users abandon the deep flow",
        "branches_explored": "4",
        "concepts": [{"term": "deep mode", "definition": "Structured interview"}],
    }
    result = validate_seed_spec(spec)
    assert result.goal == "Test deep metadata acceptance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/workflow/test_seed_parsing.py::test_validate_seed_spec_accepts_deep_interview_keys -v`
Expected: FAIL with "unknown spec key" error

- [ ] **Step 3: Add keys to ALLOWED_KEYS**

In `src/mobius/workflow/seed.py`, add to the `ALLOWED_KEYS` frozenset:

```python
"interview_mode",
"clarity_score",
"assumptions",
"premortem",
"branches_explored",
"concepts",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/workflow/test_seed_parsing.py::test_validate_seed_spec_accepts_deep_interview_keys -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/unit/workflow/test_seed_parsing.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/mobius/workflow/seed.py tests/unit/workflow/test_seed_parsing.py
git commit -m "feat(seed): add deep interview metadata keys to ALLOWED_KEYS"
```

---

### Task 2: Add deep fields to SeedSpec dataclass and normalization

**Files:**
- Modify: `src/mobius/workflow/seed.py`
- Test: `tests/unit/workflow/test_seed_parsing.py`

- [ ] **Step 1: Write failing test — deep fields are in SeedSpec and event payload**

Add to `tests/unit/workflow/test_seed_parsing.py`:

```python
def test_validate_seed_spec_stores_deep_fields_in_dataclass() -> None:
    spec = {
        "project_type": "greenfield",
        "goal": "Test deep fields storage",
        "constraints": ["Keep it simple"],
        "success_criteria": ["Fields are stored"],
        "interview_mode": "deep",
        "clarity_score": {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"},
        "assumptions": [{"statement": "Gate works", "status": "validated"}],
        "premortem": "Could fail if parser breaks",
        "branches_explored": "4",
        "concepts": [{"term": "deep", "definition": "Structured interview"}],
    }
    result = validate_seed_spec(spec)
    assert result.interview_mode == "deep"
    assert result.clarity_score == {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"}
    assert result.assumptions == [{"statement": "Gate works", "status": "validated"}]
    assert result.premortem == "Could fail if parser breaks"
    assert result.branches_explored == 4
    assert result.concepts == [{"term": "deep", "definition": "Structured interview"}]

    payload = result.to_event_payload()
    assert payload["interview_mode"] == "deep"
    assert payload["clarity_score"] == {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"}
    assert payload["premortem"] == "Could fail if parser breaks"
    assert payload["branches_explored"] == 4


def test_validate_seed_spec_deep_fields_default_empty_when_absent() -> None:
    spec = {
        "project_type": "greenfield",
        "goal": "No deep fields here",
        "constraints": ["Basic"],
        "success_criteria": ["Works"],
    }
    result = validate_seed_spec(spec)
    assert result.interview_mode == ""
    assert result.clarity_score == {}
    assert result.assumptions == []
    assert result.premortem == ""
    assert result.branches_explored == 0
    assert result.concepts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/workflow/test_seed_parsing.py::test_validate_seed_spec_stores_deep_fields_in_dataclass tests/unit/workflow/test_seed_parsing.py::test_validate_seed_spec_deep_fields_default_empty_when_absent -v`
Expected: FAIL with AttributeError (SeedSpec has no `interview_mode` etc.)

- [ ] **Step 3: Add fields to SeedSpec dataclass**

In `src/mobius/workflow/seed.py`, add to the `SeedSpec` dataclass after `spec_version`:

```python
interview_mode: str = ""
clarity_score: dict[str, str] = field(default_factory=dict)
assumptions: list[dict[str, Any]] = field(default_factory=list)
premortem: str = ""
branches_explored: int = 0
concepts: list[dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 4: Add to to_event_payload()**

In `SeedSpec.to_event_payload()`, add after the `spec_version` line:

```python
"interview_mode": self.interview_mode,
"clarity_score": dict(self.clarity_score),
"assumptions": [dict(a) for a in self.assumptions],
"premortem": self.premortem,
"branches_explored": self.branches_explored,
"concepts": [dict(c) for c in self.concepts],
```

- [ ] **Step 5: Add normalization in validate_seed_spec()**

In `validate_seed_spec()`, before the `if errors:` line, add:

```python
interview_mode = _as_text(values.get("interview_mode"))

clarity_score_raw = values.get("clarity_score")
clarity_score_val: dict[str, str] = {}
if clarity_score_raw is not None:
    try:
        clarity_score_val = _normalize_metadata(clarity_score_raw)
    except ValueError as exc:
        errors.append(str(exc))

assumptions_val: list[dict[str, Any]] = []
if "assumptions" in values:
    try:
        assumptions_val = _normalize_mapping_list(values.get("assumptions"), "assumptions")
    except ValueError as exc:
        errors.append(str(exc))

premortem_val = _as_text(values.get("premortem"))

branches_explored_val = 0
if "branches_explored" in values:
    try:
        branches_explored_val = _as_int(values.get("branches_explored"), "branches_explored")
    except ValueError as exc:
        errors.append(str(exc))

concepts_val: list[dict[str, Any]] = []
if "concepts" in values:
    try:
        concepts_val = _normalize_mapping_list(values.get("concepts"), "concepts")
    except ValueError as exc:
        errors.append(str(exc))
```

Then add the fields to the `SeedSpec(...)` constructor at the end of the function:

```python
interview_mode=interview_mode,
clarity_score=clarity_score_val,
assumptions=assumptions_val,
premortem=premortem_val,
branches_explored=branches_explored_val,
concepts=concepts_val,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/workflow/test_seed_parsing.py -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest tests/ -x -q`
Expected: All PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add src/mobius/workflow/seed.py tests/unit/workflow/test_seed_parsing.py
git commit -m "feat(seed): add deep interview fields to SeedSpec dataclass with normalization"
```

---

### Task 3: Extend render_spec_yaml() with deep metadata support

**Files:**
- Modify: `src/mobius/workflow/interview.py`
- Test: `tests/unit/workflow/test_interview.py`

- [ ] **Step 1: Write failing test — render_spec_yaml without deep metadata is unchanged**

Add to `tests/unit/workflow/test_interview.py`:

```python
def test_render_spec_yaml_without_deep_metadata_unchanged() -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="Quick mode test",
        constraints=["Stay simple"],
        success=["Spec generated"],
        context="",
    )
    score = compute_ambiguity_score(fixture)
    session_id = "interview_quick-test_abc"

    result = render_spec_yaml(session_id, fixture, score)

    assert "interview_mode" not in result
    assert "clarity_score" not in result
    assert "Quick mode test" in result
```

- [ ] **Step 2: Write failing test — render_spec_yaml with deep metadata produces enriched YAML**

Add to `tests/unit/workflow/test_interview.py`:

```python
import json


def test_render_spec_yaml_with_deep_metadata_includes_all_fields(tmp_path: Path) -> None:
    fixture = InterviewFixture(
        project_type="greenfield",
        goal="Deep mode test",
        constraints=["Challenge everything"],
        success=["Clarity >= 12/15"],
        context="",
    )
    score = compute_ambiguity_score(fixture)
    session_id = "interview_deep-test_xyz"

    deep_meta = {
        "interview_mode": "deep",
        "clarity_score": {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"},
        "risks": [{"description": "Could be too long", "severity": "medium"}],
        "assumptions": [{"statement": "Users want depth", "status": "validated"}],
        "premortem": "Failure if users abandon",
        "branches_explored": 4,
        "concepts": [{"term": "deep", "definition": "Structured interview"}],
    }
    meta_path = tmp_path / "deep-meta.json"
    meta_path.write_text(json.dumps(deep_meta), encoding="utf-8")

    result = render_spec_yaml(session_id, fixture, score, deep_metadata_path=meta_path)

    assert "interview_mode: deep" in result
    assert "clarity_score:" in result
    assert "objectif: 5" in result or '"5"' in result
    assert "premortem:" in result
    assert "branches_explored: 4" in result
    assert "concepts:" in result
    assert "Deep mode test" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/workflow/test_interview.py::test_render_spec_yaml_without_deep_metadata_unchanged tests/unit/workflow/test_interview.py::test_render_spec_yaml_with_deep_metadata_includes_all_fields -v`
Expected: FAIL (render_spec_yaml doesn't accept deep_metadata_path)

- [ ] **Step 4: Implement deep metadata support in render_spec_yaml()**

In `src/mobius/workflow/interview.py`, modify `render_spec_yaml`:

```python
def render_spec_yaml(
    session_id: str,
    fixture: InterviewFixture,
    score: AmbiguityScore,
    *,
    deep_metadata_path: Path | None = None,
) -> str:
    """Render a stable project spec YAML document."""
    lines = [
        f"session_id: {_yaml_scalar(session_id)}",
        f"project_type: {_yaml_scalar(fixture.project_type)}",
        f"template: {_yaml_scalar(fixture.template)}",
        f"ambiguity_score: {score.score}",
        f"ambiguity_gate: {score.threshold}",
        "ambiguity_components:",
    ]
    for key in score.weights:
        lines.append(f"  {key}: {score.components[key]}")
    lines.extend(
        [
            f"goal: {_yaml_scalar(fixture.goal)}",
            "constraints:",
            *_yaml_list(fixture.constraints),
            "success_criteria:",
            *_yaml_list(fixture.success),
        ]
    )
    if fixture.is_brownfield:
        lines.append(f"context: {_yaml_scalar(fixture.context)}")

    if deep_metadata_path is not None:
        deep = _load_deep_metadata(deep_metadata_path)
        lines.extend(_render_deep_metadata(deep))

    return "\n".join(lines) + "\n"


def _load_deep_metadata(path: Path) -> dict[str, Any]:
    """Load and validate a deep-metadata JSON file."""
    import json as _json

    raw = path.read_text(encoding="utf-8")
    data = _json.loads(raw)
    if not isinstance(data, dict):
        msg = "deep metadata JSON must contain an object"
        raise ValueError(msg)
    return data


def _render_deep_metadata(deep: dict[str, Any]) -> list[str]:
    """Render deep interview metadata as YAML lines."""
    lines: list[str] = []

    if "interview_mode" in deep:
        lines.append(f"interview_mode: {_yaml_scalar(str(deep['interview_mode']))}")

    if "clarity_score" in deep and isinstance(deep["clarity_score"], dict):
        lines.append("clarity_score:")
        for k, v in deep["clarity_score"].items():
            lines.append(f"  {k}: {v}")

    if "risks" in deep and isinstance(deep["risks"], list):
        lines.append("risks:")
        for risk in deep["risks"]:
            if isinstance(risk, dict):
                first = True
                for k, v in risk.items():
                    prefix = "  - " if first else "    "
                    lines.append(f"{prefix}{k}: {_yaml_scalar(str(v))}")
                    first = False

    if "assumptions" in deep and isinstance(deep["assumptions"], list):
        lines.append("assumptions:")
        for assumption in deep["assumptions"]:
            if isinstance(assumption, dict):
                first = True
                for k, v in assumption.items():
                    prefix = "  - " if first else "    "
                    lines.append(f"{prefix}{k}: {_yaml_scalar(str(v))}")
                    first = False

    if "premortem" in deep:
        lines.append(f"premortem: {_yaml_scalar(str(deep['premortem']))}")

    if "branches_explored" in deep:
        lines.append(f"branches_explored: {deep['branches_explored']}")

    if "concepts" in deep and isinstance(deep["concepts"], list):
        lines.append("concepts:")
        for concept in deep["concepts"]:
            if isinstance(concept, dict):
                first = True
                for k, v in concept.items():
                    prefix = "  - " if first else "    "
                    lines.append(f"{prefix}{k}: {_yaml_scalar(str(v))}")
                    first = False

    return lines
```

Add `from typing import Any` to imports if not already present.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/workflow/test_interview.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/mobius/workflow/interview.py tests/unit/workflow/test_interview.py
git commit -m "feat(interview): add deep metadata support to render_spec_yaml"
```

---

### Task 4: Add --deep-metadata CLI flag

**Files:**
- Modify: `src/mobius/cli/commands/interview.py`
- Test: `tests/e2e/cli/test_interview_command.py`

- [ ] **Step 1: Write failing test — deep metadata flag produces enriched spec**

Add to `tests/e2e/cli/test_interview_command.py`:

```python
def test_interview_non_interactive_with_deep_metadata_enriches_spec(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    fixture = tmp_path / "fixture.yaml"
    spec = tmp_path / "spec.yaml"
    deep_meta = tmp_path / "deep-meta.json"

    fixture.write_text(
        """
project_type: greenfield
goal: Build an enriched interview flow.
constraints:
  - Keep backward compat
success:
  - Deep metadata appears in spec
""".strip(),
        encoding="utf-8",
    )

    deep_meta.write_text(
        json.dumps({
            "interview_mode": "deep",
            "clarity_score": {"objectif": "5", "comment": "4", "criteres": "4", "total": "13"},
            "risks": [{"description": "Might be complex", "severity": "medium"}],
            "assumptions": [{"statement": "Users want this", "status": "validated"}],
            "premortem": "Failure if too long",
            "branches_explored": 3,
            "concepts": [{"term": "deep", "definition": "Structured"}],
        }),
        encoding="utf-8",
    )

    result = run_mobius(
        "--json",
        "interview",
        "--non-interactive",
        "--input",
        str(fixture),
        "--output",
        str(spec),
        "--deep-metadata",
        str(deep_meta),
        mobius_home=mobius_home,
    )

    assert result.returncode == 0
    spec_text = spec.read_text(encoding="utf-8")
    assert "interview_mode: deep" in spec_text
    assert "clarity_score:" in spec_text
    assert "premortem:" in spec_text
    assert "branches_explored: 3" in spec_text
    assert "concepts:" in spec_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/e2e/cli/test_interview_command.py::test_interview_non_interactive_with_deep_metadata_enriches_spec -v`
Expected: FAIL (no such option --deep-metadata)

- [ ] **Step 3: Add --deep-metadata flag to CLI**

In `src/mobius/cli/commands/interview.py`, modify the `run()` function signature to add:

```python
deep_metadata: Path | None = None,
```

Then in the body, pass it to `render_spec_yaml`:

```python
spec_yaml = render_spec_yaml(session_id, fixture, score, deep_metadata_path=deep_metadata)
```

In `src/mobius/cli/main.py` (or wherever the Typer command is registered), add the option:

```python
typer.Option(None, "--deep-metadata", help="Path to a JSON file with deep interview metadata.")
```

Check how other optional Path flags are registered (like `--input`, `--output`) and follow the same pattern.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/e2e/cli/test_interview_command.py::test_interview_non_interactive_with_deep_metadata_enriches_spec -v`
Expected: PASS

- [ ] **Step 5: Run existing interview tests for non-regression**

Run: `uv run pytest tests/e2e/cli/test_interview_command.py -v`
Expected: All PASS (existing tests unaffected)

- [ ] **Step 6: Commit**

```bash
git add src/mobius/cli/commands/interview.py src/mobius/cli/main.py tests/e2e/cli/test_interview_command.py
git commit -m "feat(cli): add --deep-metadata flag to interview command"
```

---

### Task 5: End-to-end test — deep spec passes seed validation

**Files:**
- Test: `tests/e2e/cli/test_seed_command.py`

- [ ] **Step 1: Write failing test — seed accepts spec with deep metadata**

Add to `tests/e2e/cli/test_seed_command.py`:

```python
def test_seed_accepts_spec_with_deep_interview_metadata(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
session_id: interview_deep-test
project_type: greenfield
ambiguity_score: 0.0
ambiguity_gate: 0.2
ambiguity_components:
  goal: 0.0
  constraints: 0.0
  success: 0.0
goal: Test deep metadata round-trip through seed.
constraints:
  - Keep backward compat
success_criteria:
  - Seed accepts deep keys
interview_mode: deep
clarity_score:
  objectif: 5
  comment: 4
  criteres: 4
  total: 13
risks:
  - description: Could be complex
    severity: medium
assumptions:
  - statement: Users want depth
    status: validated
premortem: Failure if abandoned
branches_explored: 4
concepts:
  - term: deep mode
    definition: Structured interview with scoring
""".strip(),
        encoding="utf-8",
    )

    result = run_mobius("--json", "seed", str(spec), mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].startswith("seed_")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/e2e/cli/test_seed_command.py::test_seed_accepts_spec_with_deep_interview_metadata -v`
Expected: PASS (if Tasks 1-2 were implemented correctly)

- [ ] **Step 3: Write test — seed rejects invalid deep metadata types**

Add to `tests/e2e/cli/test_seed_command.py`:

```python
def test_seed_rejects_spec_with_invalid_deep_metadata_types(tmp_path: Path) -> None:
    spec = tmp_path / "bad_deep.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Test invalid deep metadata
constraints:
  - Basic
success_criteria:
  - Works
assumptions: not-a-list
""".strip(),
        encoding="utf-8",
    )

    result = run_mobius("seed", str(spec), mobius_home=tmp_path / "home")

    assert result.returncode == 3
    assert "assumptions" in result.stderr
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/e2e/cli/test_seed_command.py::test_seed_rejects_spec_with_invalid_deep_metadata_types -v`
Expected: PASS

- [ ] **Step 5: Run full seed test suite**

Run: `uv run pytest tests/e2e/cli/test_seed_command.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/e2e/cli/test_seed_command.py
git commit -m "test(e2e): add seed validation tests for deep interview metadata"
```

---

### Task 6: Rewrite the interview skill.md with quick/deep modes

**Files:**
- Modify: `src/mobius/integration/assets/skills/interview/skill.md`

- [ ] **Step 1: Read the current skill.md**

Read `src/mobius/integration/assets/skills/interview/skill.md` to confirm the current content before overwriting.

- [ ] **Step 2: Write the new skill.md**

Replace `src/mobius/integration/assets/skills/interview/skill.md` with the unified skill containing:

**Frontmatter:**
```yaml
---
name: interview
description: "Drive the user through a project-discovery conversation, then record the resulting spec via mobius interview --non-interactive. Two modes: deep (default) — structured interview with scoring, anti-complacency, and pre-mortem; quick — fast extraction for clear projects. Triggers: interview, start project, set up project, build X, track this work."
---
```

**Section 1: Base commune** (~30 lines)
- When to use / when not to use
- Workspace scan (template detection table)
- Never invoke via MCP rule
- Routing table: `/interview` → deep, `/interview quick` → quick, `/interview deep` → deep

**Section 2: Mode Quick** (~50 lines)
- The current skill content verbatim (conversation → extract → CLI → spec.yaml)
- Worked example

**Section 3: Mode Deep** (~250 lines)
- Phase 1: Vision (type detection, maturity, reformulation, gate)
- Phase 2: Cartographie (branches, arbre, gate)
- Phase 3: Exploration (scoring format, anti-complacency patterns BAD/GOOD, push twice, routing per question, smart-skip, forcing questions per domain, concept registry, Phase 3.5 perspective change, Phase 3.7 web research, gate)
- Phase 4: Challenge (hidden assumptions, pre-mortem, Phase 4.5 second opinion via sub-agent, gate >= 12/15)
- Phase 5: Extraction (checklist, mapping to spec.yaml fields, write deep-meta.json, call CLI with --deep-metadata, gate d'ambiguïté handling)
- Scoring de clarté (3 axes tables: Objectif/Comment/Critères, targeting rules, rise/fall rules)
- Rules (one question at a time, French default, early exit, progression display)

**Section 4: What NOT to do**
- No MCP
- No flat constraints
- No skipping conversation
- No inventing fixture files

Full content should be written following the design spec at `docs/superpowers/specs/2026-04-29-interview-v2-design.md`. Include all 10 mechanics from `/entrevue` as documented in the spec.

- [ ] **Step 3: Verify the symlink still works**

Run: `ls -la /Users/charles/Desktop/Mobius/skills/interview/skill.md`
The `skills` symlink at project root points to `src/mobius/integration/assets/skills`. Verify the file is accessible through both paths.

- [ ] **Step 4: Commit**

```bash
git add src/mobius/integration/assets/skills/interview/skill.md
git commit -m "feat(skill): rewrite interview skill with unified quick/deep modes"
```

---

### Task 7: Full regression test suite

**Files:**
- No new files

- [ ] **Step 1: Run unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 2: Run e2e tests**

Run: `uv run pytest tests/e2e/ -v`
Expected: All PASS

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/mobius/`
Expected: No errors

- [ ] **Step 4: Run linter**

Run: `uv run ruff check src/mobius/`
Expected: No errors

- [ ] **Step 5: Verify coverage**

Run: `uv run pytest tests/ --cov=src/mobius --cov-fail-under=95`
Expected: Coverage >= 95%

- [ ] **Step 6: Manual smoke test**

Run: `uv run mobius interview --help`
Verify: `--deep-metadata` appears in the help output.

Run: `uv run mobius interview --non-interactive --goal "Test smoke" --constraint "None" --success-criterion "Works" --output /tmp/smoke-spec.yaml`
Verify: `/tmp/smoke-spec.yaml` is generated and does NOT contain deep fields.

- [ ] **Step 7: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address regression test findings"
```
