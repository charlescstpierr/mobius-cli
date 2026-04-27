"""Deterministic interview engine and spec rendering.

The interview turns a set of structured questions and answers into a valid
``spec.yaml``. It supports three input modes:

1. **Interactive (TTY)** — prompts the user one question at a time on stderr
   and reads answers from stdin. Uses the auto-detected or ``--template``
   defaults so users can press Enter to accept the recommendation.
2. **Scripted stdin** — same prompts, but answers come from a non-TTY stdin
   (an ``expect`` script or shell here-doc), one answer per line. Empty
   lines accept the default.
3. **Non-interactive fixture** — ``--non-interactive --input fixture.yaml``
   reads a deterministic answers file, no prompts emitted. Existing CI
   behaviour is preserved.

Mobius does not execute anything; the interview only writes a spec file.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from mobius.workflow.templates import (
    TEMPLATE_NAMES,
    ProjectTemplate,
    detect_template,
    get_template,
)

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
    template: str = "blank"

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
    """Parse a deterministic fixture from JSON or a small YAML subset."""
    raw = path.read_text(encoding="utf-8")
    values = _parse_mapping(raw)
    project_type = str(values.get("project_type", "greenfield")).strip().lower()
    if project_type not in {"greenfield", "brownfield"}:
        msg = "project_type must be either 'greenfield' or 'brownfield'"
        raise ValueError(msg)
    template = str(values.get("template", "blank")).strip().lower() or "blank"
    if template not in TEMPLATE_NAMES:
        template = "blank"
    return InterviewFixture(
        project_type=project_type,
        goal=_as_text(values.get("goal")),
        constraints=_as_text_list(values.get("constraints")),
        success=_as_text_list(values.get("success")),
        context=_as_text(values.get("context")),
        template=template,
    )


def fixture_from_template(
    template: ProjectTemplate, *, project_type: str = "greenfield"
) -> InterviewFixture:
    """Build a fixture pre-populated from a template (used as defaults)."""
    return InterviewFixture(
        project_type=project_type,
        goal=template.goal,
        constraints=list(template.constraints),
        success=list(template.success_criteria),
        context="",
        template=template.name,
    )


def run_interactive_interview(
    *,
    workspace: Path,
    template_name: str | None = None,
    project_type: str = "greenfield",
    stdin: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> InterviewFixture:
    """Drive the user through the interview and return a fixture.

    Prompts go to ``stderr`` (so stdout stays clean); answers come from
    ``stdin``. Empty answers accept the default. The function works the
    same for TTY and scripted stdin — when stdin reaches EOF before all
    questions are answered, remaining defaults are used.
    """
    in_stream = stdin if stdin is not None else sys.stdin
    err = stderr if stderr is not None else sys.stderr

    if template_name is None:
        template_name = detect_template(workspace)
    template = get_template(template_name)
    defaults = fixture_from_template(template, project_type=project_type)

    err.write(f"# Mobius interview — template: {template.name}\n")
    err.write(f"# {template.description}\n")
    err.write("# Press Enter to accept the [default] in brackets.\n\n")
    err.flush()

    project_type_answer = _prompt_choice(
        err,
        in_stream,
        "Project type [greenfield/brownfield]",
        default=defaults.project_type,
        choices=("greenfield", "brownfield"),
    )
    goal_answer = _prompt_scalar(
        err, in_stream, "Goal — what should this project ship?", default=defaults.goal
    )
    constraints_answer = _prompt_list(
        err,
        in_stream,
        "Constraints (one per line, blank line to finish)",
        defaults=defaults.constraints,
    )
    success_answer = _prompt_list(
        err,
        in_stream,
        "Success criteria (one per line, blank line to finish)",
        defaults=defaults.success,
    )
    context_answer = ""
    if project_type_answer == "brownfield":
        context_answer = _prompt_scalar(
            err,
            in_stream,
            "Existing context to preserve",
            default=defaults.context or "Existing system in place; preserve current behavior.",
        )

    return InterviewFixture(
        project_type=project_type_answer,
        goal=goal_answer,
        constraints=constraints_answer,
        success=success_answer,
        context=context_answer,
        template=template.name,
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
    return "\n".join(lines) + "\n"


def question_answers(fixture: InterviewFixture) -> list[tuple[str, str, str | list[str]]]:
    """Return deterministic question/answer triples for persistence events."""
    answers: list[tuple[str, str, str | list[str]]] = [
        ("project_type", "What kind of project is this?", fixture.project_type),
        ("template", "Which template best fits this project?", fixture.template),
        ("goal", "What goal should this project accomplish?", fixture.goal),
        ("constraints", "What constraints must the solution respect?", fixture.constraints),
        ("success", "What outcomes prove success?", fixture.success),
    ]
    if fixture.is_brownfield:
        answers.append(("context", "What existing context must be preserved?", fixture.context))
    return answers


def _prompt_scalar(err: IO[str], in_stream: IO[str], question: str, *, default: str) -> str:
    err.write(f"{question}\n  [default: {default!r}]\n> ")
    err.flush()
    line = in_stream.readline()
    if line == "":
        return default
    answer = line.rstrip("\n").strip()
    return answer if answer else default


def _prompt_choice(
    err: IO[str],
    in_stream: IO[str],
    question: str,
    *,
    default: str,
    choices: tuple[str, ...],
) -> str:
    while True:
        err.write(f"{question}\n  [default: {default}]\n> ")
        err.flush()
        line = in_stream.readline()
        if line == "":
            return default
        answer = line.rstrip("\n").strip().lower() or default
        if answer in choices:
            return answer
        err.write(f"  not a valid choice ({', '.join(choices)}); try again.\n")


def _prompt_list(
    err: IO[str], in_stream: IO[str], question: str, *, defaults: list[str]
) -> list[str]:
    err.write(f"{question}\n")
    if defaults:
        err.write("  defaults (Enter on first prompt to accept all):\n")
        for default in defaults:
            err.write(f"    - {default}\n")
    err.write("> ")
    err.flush()
    first_line = in_stream.readline()
    if first_line == "":
        return list(defaults)
    first = first_line.rstrip("\n").strip()
    if first == "":
        return list(defaults)

    answers = [first]
    while True:
        err.write("> ")
        err.flush()
        line = in_stream.readline()
        if line == "":
            break
        item = line.rstrip("\n").strip()
        if item == "":
            break
        answers.append(item)
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


# Re-export for test convenience.
StringIO = io.StringIO
