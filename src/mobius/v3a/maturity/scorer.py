"""Mechanical v3a maturity scoring and top-up helpers.

The scorer is intentionally deterministic and local-only: it reads the v2
``spec.yaml`` shape, computes four bounded readiness dimensions, and never calls
an LLM or subprocess.  The fourth dimension folds in the rolling-window lemma
metric required by v3a so the public breakdown remains the contractually
specified four keys.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mobius.v3a.interview.lemma_check import extract_lemmas
from mobius.workflow.seed import SeedSpec, load_seed_spec

MATURITY_THRESHOLD = 0.8
_EDGE_CASE_RE = re.compile(
    r"\b(edge|empty|invalid|malformed|error|failure|fail|timeout|missing|"
    r"partial|permission|fallback|corner|boundary|offline)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MaturityReport:
    """A complete mechanical maturity result."""

    score: float
    breakdown: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Return whether the report satisfies the v3a maturity gate."""
        return self.score >= MATURITY_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        return {
            "score": self.score,
            "passed": self.passed,
            "threshold": MATURITY_THRESHOLD,
            "breakdown": dict(self.breakdown),
            "details": json.loads(json.dumps(self.details, sort_keys=True)),
        }


@dataclass(frozen=True)
class MaturityTopUp:
    """Result of a deterministic auto-top-up pass."""

    spec_path: Path
    questions_asked: int
    before: MaturityReport
    after: MaturityReport


class MaturityGateError(RuntimeError):
    """Raised when an immature spec is blocked by the Phase 3 gate."""

    def __init__(self, report: MaturityReport) -> None:
        super().__init__(
            f"maturity score {report.score:.2f} is below required "
            f"{MATURITY_THRESHOLD:.2f}; use --auto-top-up or --force-immature"
        )
        self.report = report


def score_spec(spec: SeedSpec | Path) -> MaturityReport:
    """Compute the deterministic v3a maturity score for ``spec``."""
    loaded = load_seed_spec(spec) if isinstance(spec, Path) else spec
    criteria = loaded.success_criteria
    criteria_count = len(criteria)
    verification_ratio = _verification_ratio(loaded)
    edge_case_ratio = _edge_case_ratio(loaded)
    constraint_ratio = _constraint_coverage_ratio(loaded)
    ambiguity_lemma_ratio = _ambiguity_and_lemma_ratio(loaded)
    breakdown = {
        "verification_coverage": _target_score(verification_ratio, 0.95),
        "edge_case_coverage": _target_score(edge_case_ratio, 0.80),
        "constraint_coverage": constraint_ratio,
        "ambiguity_and_lemma": ambiguity_lemma_ratio,
    }
    score = round(sum(breakdown.values()) / len(breakdown), 3)
    return MaturityReport(
        score=max(0.0, min(1.0, score)),
        breakdown={key: round(value, 3) for key, value in breakdown.items()},
        details={
            "criteria_count": criteria_count,
            "verification_ratio": round(verification_ratio, 3),
            "edge_case_ratio": round(edge_case_ratio, 3),
            "constraint_ratio": round(constraint_ratio, 3),
            "ambiguity_lemma_ratio": round(ambiguity_lemma_ratio, 3),
            "rolling_lemma_metric": round(_rolling_lemma_metric(criteria), 3),
        },
    )


def top_up_spec_to_threshold(spec_path: Path) -> MaturityTopUp:
    """Apply the minimum deterministic question/top-up needed to reach 0.8.

    Each pass answers one synthetic Socrate question by adding the smallest
    missing readiness artifact in priority order: verification command,
    edge-case criterion, constraint reference, then lemma novelty.  The loop is
    bounded by the number of criteria plus a small constant and is deterministic.
    """
    before = score_spec(spec_path)
    if before.passed:
        return MaturityTopUp(spec_path, 0, before, before)

    spec = load_seed_spec(spec_path)
    questions = 0
    current = before
    max_questions = max(4, len(spec.success_criteria) + len(spec.constraints) + 4)
    while not current.passed and questions < max_questions:
        spec = _top_up_once(spec)
        questions += 1
        current = score_spec(spec)

    _write_seed_spec(spec_path, spec)
    after = score_spec(spec_path)
    return MaturityTopUp(spec_path, questions, before, after)


def render_report(report: MaturityReport) -> str:
    """Render a compact human-readable maturity report."""
    lines = [
        "# Mobius v3a Maturity Report",
        "",
        f"score: {report.score:.3f}",
        f"threshold: {MATURITY_THRESHOLD:.3f}",
        f"passed: {str(report.passed).lower()}",
        "",
        "breakdown:",
    ]
    lines.extend(f"  {key}: {value:.3f}" for key, value in report.breakdown.items())
    lines.extend(["", "details:"])
    lines.extend(f"  {key}: {value}" for key, value in report.details.items())
    return "\n".join(lines) + "\n"


def _verification_ratio(spec: SeedSpec) -> float:
    criteria_count = len(spec.success_criteria)
    if criteria_count == 0:
        return 0.0
    covered = 0
    for index, criterion in enumerate(spec.success_criteria, start=1):
        references = _criterion_references(index, criterion)
        if any(_command_matches(command, references) for command in spec.verification_commands):
            covered += 1
    return covered / criteria_count


def _edge_case_ratio(spec: SeedSpec) -> float:
    criteria_count = len(spec.success_criteria)
    if criteria_count == 0:
        return 0.0
    edgeful = sum(1 for criterion in spec.success_criteria if _EDGE_CASE_RE.search(criterion))
    risk_edgeful = sum(
        1 for risk in spec.risks if _EDGE_CASE_RE.search(" ".join(str(v) for v in risk.values()))
    )
    return min(1.0, (edgeful + risk_edgeful) / criteria_count)


def _constraint_coverage_ratio(spec: SeedSpec) -> float:
    if not spec.constraints:
        return 0.0
    searchable = " ".join(
        [
            spec.goal,
            spec.context,
            *spec.success_criteria,
            *[" ".join(str(v) for v in command.values()) for command in spec.verification_commands],
            *[" ".join(str(v) for v in risk.values()) for risk in spec.risks],
        ]
    ).lower()
    covered = 0
    for constraint in spec.constraints:
        lemmas = extract_lemmas(constraint)
        if not lemmas or any(lemma in searchable for lemma in lemmas):
            covered += 1
    return covered / len(spec.constraints)


def _ambiguity_and_lemma_ratio(spec: SeedSpec) -> float:
    ambiguity = _metadata_float(spec, "ambiguity_score", default=0.0)
    ambiguity_readiness = 1.0 - min(1.0, ambiguity / 0.2)
    return (ambiguity_readiness + _rolling_lemma_metric(spec.success_criteria)) / 2.0


def _metadata_float(spec: SeedSpec, key: str, *, default: float) -> float:
    raw = spec.metadata.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _rolling_lemma_metric(criteria: list[str], *, window: int = 5) -> float:
    if not criteria:
        return 0.0
    previous: list[str] = []
    novel = 0
    for criterion in criteria:
        current = extract_lemmas(criterion)
        recent: set[str] = set()
        for prior in previous[-window:]:
            recent.update(extract_lemmas(prior))
        if current - recent:
            novel += 1
        previous.append(criterion)
    return novel / len(criteria)


def _target_score(actual_ratio: float, target_ratio: float) -> float:
    if target_ratio <= 0:
        return 1.0
    return max(0.0, min(1.0, actual_ratio / target_ratio))


def _criterion_references(index: int, criterion: str) -> set[str]:
    return {
        str(index),
        f"criterion-{index}",
        f"success-{index}",
        f"sc-{index}",
        criterion,
    }


def _command_matches(command: dict[str, Any], references: set[str]) -> bool:
    raw_ref = str(command.get("criterion_ref", "")).strip()
    if raw_ref in references:
        return True
    command_text = " ".join(str(value) for value in command.values()).lower()
    return any(reference.lower() in command_text for reference in references if len(reference) > 8)


def _top_up_once(spec: SeedSpec) -> SeedSpec:
    if _verification_ratio(spec) < 0.95:
        return _add_missing_verification(spec)
    if _edge_case_ratio(spec) < 0.80:
        return _add_edge_case_criterion(spec)
    if _constraint_coverage_ratio(spec) < 1.0:
        return _add_constraint_coverage_criterion(spec)
    return _add_lemma_novelty_criterion(spec)


def _add_missing_verification(spec: SeedSpec) -> SeedSpec:
    commands = [dict(command) for command in spec.verification_commands]
    for index, criterion in enumerate(spec.success_criteria, start=1):
        references = _criterion_references(index, criterion)
        if not any(_command_matches(command, references) for command in commands):
            commands.append(
                {
                    "command": "uv run pytest -q",
                    "timeout_s": 60,
                    "criterion_ref": str(index),
                    "shell": True,
                }
            )
            break
    return _replace_spec(spec, verification_commands=commands)


def _add_edge_case_criterion(spec: SeedSpec) -> SeedSpec:
    risks = [dict(risk) for risk in spec.risks]
    risks.append(
        {
            "description": "Edge case: invalid or empty input fails with a clear error message.",
            "severity": "low",
            "mitigation": "Add or run a deterministic test for the invalid-input path.",
        }
    )
    return _replace_spec(spec, risks=risks)


def _add_constraint_coverage_criterion(spec: SeedSpec) -> SeedSpec:
    criteria = list(spec.success_criteria)
    uncovered = spec.constraints[0] if spec.constraints else "Document implementation constraints."
    criteria.append(f"Constraint coverage: implementation explicitly preserves {uncovered}")
    commands = [dict(command) for command in spec.verification_commands]
    commands.append(
        {
            "command": "uv run pytest -q",
            "timeout_s": 60,
            "criterion_ref": str(len(criteria)),
            "shell": True,
        }
    )
    return _replace_spec(spec, success_criteria=criteria, verification_commands=commands)


def _add_lemma_novelty_criterion(spec: SeedSpec) -> SeedSpec:
    criteria = list(spec.success_criteria)
    criteria.append("Operational telemetry records readiness, rollback, and recovery outcomes.")
    commands = [dict(command) for command in spec.verification_commands]
    commands.append(
        {
            "command": "uv run pytest -q",
            "timeout_s": 60,
            "criterion_ref": str(len(criteria)),
            "shell": True,
        }
    )
    return _replace_spec(spec, success_criteria=criteria, verification_commands=commands)


def _replace_spec(
    spec: SeedSpec,
    *,
    success_criteria: list[str] | None = None,
    verification_commands: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
) -> SeedSpec:
    return SeedSpec(
        source_session_id=spec.source_session_id,
        project_type=spec.project_type,
        goal=spec.goal,
        constraints=list(spec.constraints),
        success_criteria=(
            success_criteria if success_criteria is not None else list(spec.success_criteria)
        ),
        context=spec.context,
        steps=list(spec.steps),
        matrix={key: list(values) for key, values in spec.matrix.items()},
        metadata=dict(spec.metadata),
        template=spec.template,
        non_goals=list(spec.non_goals),
        verification_commands=(
            verification_commands
            if verification_commands is not None
            else [dict(command) for command in spec.verification_commands]
        ),
        risks=risks if risks is not None else [dict(risk) for risk in spec.risks],
        artifacts=[dict(artifact) for artifact in spec.artifacts],
        owner=list(spec.owner) if isinstance(spec.owner, list) else spec.owner,
        agent_instructions=(
            dict(spec.agent_instructions)
            if isinstance(spec.agent_instructions, dict)
            else spec.agent_instructions
        ),
        spec_version=spec.spec_version,
    )


def _write_seed_spec(path: Path, spec: SeedSpec) -> None:
    path.write_text(_render_seed_spec(spec), encoding="utf-8")


def _render_seed_spec(spec: SeedSpec) -> str:
    lines = [f"spec_version: {spec.spec_version}"]
    if spec.source_session_id:
        lines.append(f"session_id: {_yaml_scalar(spec.source_session_id)}")
    lines.append(f"project_type: {_yaml_scalar(spec.project_type)}")
    if spec.template:
        lines.append(f"template: {_yaml_scalar(spec.template)}")
    lines.extend(
        [
            f"goal: {_yaml_scalar(spec.goal)}",
            "constraints:",
            *_yaml_list(spec.constraints),
            "success_criteria:",
            *_yaml_list(spec.success_criteria),
        ]
    )
    if spec.context:
        lines.append(f"context: {_yaml_scalar(spec.context)}")
    if spec.non_goals:
        lines.extend(["non_goals:", *_yaml_list(spec.non_goals)])
    if spec.verification_commands:
        lines.append("verification_commands:")
        for command in spec.verification_commands:
            lines.append(f"  - command: {_yaml_scalar(str(command.get('command', '')))}")
            for key in ("timeout_s", "criterion_ref", "shell"):
                if key in command:
                    lines.append(f"    {key}: {_yaml_scalar(command[key])}")
    if spec.risks:
        lines.append("risks:")
        for risk in spec.risks:
            lines.append(f"  - description: {_yaml_scalar(str(risk.get('description', '')))}")
            for key in ("severity", "mitigation"):
                if key in risk:
                    lines.append(f"    {key}: {_yaml_scalar(risk[key])}")
    if spec.owner:
        if isinstance(spec.owner, list):
            lines.extend(["owner:", *_yaml_list(spec.owner)])
        else:
            lines.append(f"owner: {_yaml_scalar(spec.owner)}")
    if spec.agent_instructions:
        lines.append(f"agent_instructions: {_yaml_scalar(spec.agent_instructions)}")
    return "\n".join(lines) + "\n"


def _yaml_list(values: list[str]) -> list[str]:
    return [f"  - {_yaml_scalar(value)}" for value in values]


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    needs_quotes = (
        any(char in text for char in (":", "#", "{", "}", "[", "]"))
        or text != text.strip()
    )
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if needs_quotes else escaped
