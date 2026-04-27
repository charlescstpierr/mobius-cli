"""Deterministic interview fixture parsing, scoring, and spec rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_GATE_THRESHOLD = 0.2
_AMBIGUOUS_MARKERS = frozenset({"", "tbd", "todo", "unknown", "unclear", "n/a", "na", "?"})


@dataclass(frozen=True)
class InterviewFixture:
    """Deterministic non-interactive interview answers."""

    project_type: str
    goal: str
    constraints: list[str]
    success: list[str]
    context: str

    @property
    def is_brownfield(self) -> bool:
        """Return whether context should participate in ambiguity scoring."""
        return self.project_type == "brownfield"


@dataclass(frozen=True)
class AmbiguityScore:
    """Weighted ambiguity score for an interview."""

    score: float
    threshold: float
    passed: bool
    weights: dict[str, float]
    components: dict[str, float]

    def raise_for_gate(self) -> None:
        """Raise if the ambiguity gate is not satisfied."""
        if not self.passed:
            msg = (
                f"ambiguity score {self.score:.3f} exceeds gate "
                f"{self.threshold:.3f}; provide clearer fixture answers"
            )
            raise AmbiguityGateError(msg)


class AmbiguityGateError(ValueError):
    """Raised when an interview cannot produce a spec due to ambiguity."""


def parse_fixture(path: Path) -> InterviewFixture:
    """Parse a deterministic fixture from JSON or a small YAML subset.

    The mission fixture format intentionally stays dependency-free. Supported
    YAML is a top-level mapping whose values are scalars or ``-`` item lists.
    JSON object fixtures with the same keys are also accepted.
    """
    raw = path.read_text(encoding="utf-8")
    values = _parse_mapping(raw)
    project_type = str(values.get("project_type", "greenfield")).strip().lower()
    if project_type not in {"greenfield", "brownfield"}:
        msg = "project_type must be either 'greenfield' or 'brownfield'"
        raise ValueError(msg)
    return InterviewFixture(
        project_type=project_type,
        goal=_as_text(values.get("goal")),
        constraints=_as_text_list(values.get("constraints")),
        success=_as_text_list(values.get("success")),
        context=_as_text(values.get("context")),
    )


def compute_ambiguity_score(fixture: InterviewFixture) -> AmbiguityScore:
    """Compute the weighted ambiguity score for a fixture."""
    weights = (
        {"goal": 0.3, "constraints": 0.25, "success": 0.25, "context": 0.2}
        if fixture.is_brownfield
        else {"goal": 0.4, "constraints": 0.3, "success": 0.3}
    )
    components = {
        "goal": _ambiguity_for_scalar(fixture.goal),
        "constraints": _ambiguity_for_list(fixture.constraints),
        "success": _ambiguity_for_list(fixture.success),
    }
    if fixture.is_brownfield:
        components["context"] = _ambiguity_for_scalar(fixture.context)
    score = round(sum(weights[key] * components[key] for key in weights), 3)
    return AmbiguityScore(
        score=score,
        threshold=_GATE_THRESHOLD,
        passed=score <= _GATE_THRESHOLD,
        weights=weights,
        components=components,
    )


def render_spec_yaml(session_id: str, fixture: InterviewFixture, score: AmbiguityScore) -> str:
    """Render a stable project spec YAML document."""
    lines = [
        f"session_id: {_yaml_scalar(session_id)}",
        f"project_type: {_yaml_scalar(fixture.project_type)}",
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
    return "\n".join(lines) + "\n"


def question_answers(fixture: InterviewFixture) -> list[tuple[str, str, str | list[str]]]:
    """Return deterministic question/answer triples for persistence events."""
    answers: list[tuple[str, str, str | list[str]]] = [
        ("goal", "What goal should this project accomplish?", fixture.goal),
        ("constraints", "What constraints must the solution respect?", fixture.constraints),
        ("success", "What outcomes prove success?", fixture.success),
    ]
    if fixture.is_brownfield:
        answers.append(("context", "What existing context must be preserved?", fixture.context))
    return answers


def _parse_mapping(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            msg = "fixture JSON must contain an object"
            raise ValueError(msg)
        return dict(parsed)
    return _parse_simple_yaml(stripped)


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list_key is None:
                msg = f"list item without preceding key: {line}"
                raise ValueError(msg)
            value = _strip_quotes(stripped[2:].strip())
            cast_list = result.setdefault(current_list_key, [])
            if not isinstance(cast_list, list):
                msg = f"key {current_list_key!r} cannot contain both scalar and list values"
                raise ValueError(msg)
            cast_list.append(value)
            continue
        if ":" not in stripped:
            msg = f"unsupported fixture line: {line}"
            raise ValueError(msg)
        key, value = stripped.split(":", 1)
        current_list_key = None
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_value == "":
            result[normalized_key] = []
            current_list_key = normalized_key
        else:
            result[normalized_key] = _strip_quotes(normalized_value)
    return result


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _as_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _ambiguity_for_scalar(value: str) -> float:
    return 1.0 if _is_ambiguous(value) else 0.0


def _ambiguity_for_list(values: list[str]) -> float:
    if not values:
        return 1.0
    ambiguous = sum(1 for value in values if _is_ambiguous(value))
    return round(ambiguous / len(values), 3)


def _is_ambiguous(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _AMBIGUOUS_MARKERS or normalized.startswith(("tbd", "todo"))


def _yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    special = any(character in value for character in ":#[]{}&*!|>'\"%@`")
    if special or value != value.strip() or "\n" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _yaml_list(values: list[str]) -> list[str]:
    if not values:
        return ["  []"]
    return [f"  - {_yaml_scalar(value)}" for value in values]
