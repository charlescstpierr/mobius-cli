"""Seed spec parsing and validation for the Mobius workflow."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_MAX_SPEC_BYTES = 256 * 1024
_MAX_NESTING_DEPTH = 4
_ANCHOR_RE = re.compile(r"(^|[\s:\[,])&[A-Za-z0-9_-]+")
_REFERENCE_RE = re.compile(r"(^|[\s:\[,])\*[A-Za-z0-9_-]+")

# Top-level keys recognised by the seed-spec validator. Mobius does not execute
# any commands itself, so all keys are descriptive metadata. ``steps`` and
# ``matrix`` were added in v0.1.4 to let users express ordered work and
# multi-axis projects without flattening them into a single bullet list.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "session_id",
        "project_type",
        "goal",
        "constraints",
        "success_criteria",
        "success",
        "context",
        "steps",
        "matrix",
        "metadata",
        "template",
        "non_goals",
        "verification_commands",
        "risks",
        "artifacts",
        "owner",
        "agent_instructions",
        "spec_version",
        # Interview-rendered fields kept for round-tripping.
        "ambiguity_score",
        "ambiguity_gate",
        "ambiguity_components",
        # Deep interview metadata (v2).
        "interview_mode",
        "clarity_score",
        "assumptions",
        "premortem",
        "branches_explored",
        "concepts",
    }
)


class SeedSpecValidationError(ValueError):
    """Raised when a seed spec cannot be accepted."""


class SpecParseError(ValueError):
    """Raised when the custom seed-spec parser rejects unsupported input."""


@dataclass(frozen=True)
class SeedStep:
    """One ordered step in a Mobius spec.

    Mobius does not execute the ``command``; it is recorded as descriptive
    metadata so agents and CI wrappers can drive the actual work while
    Mobius keeps the event/lineage trail.
    """

    name: str
    command: str = ""
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedSpec:
    """Validated input used to create a seed session."""

    source_session_id: str | None
    project_type: str
    goal: str
    constraints: list[str]
    success_criteria: list[str]
    context: str
    steps: list[SeedStep] = field(default_factory=list)
    matrix: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    template: str = ""
    non_goals: list[str] = field(default_factory=list)
    verification_commands: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    owner: str | list[str] = ""
    agent_instructions: str | dict[str, str] = ""
    spec_version: int = 2
    interview_mode: str = ""
    clarity_score: dict[str, str] = field(default_factory=dict)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    premortem: str = ""
    branches_explored: int = 0
    concepts: list[dict[str, Any]] = field(default_factory=list)

    def to_event_payload(self) -> dict[str, Any]:
        """Return a JSON-compatible payload for event persistence."""
        return {
            "source_session_id": self.source_session_id,
            "project_type": self.project_type,
            "goal": self.goal,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
            "context": self.context,
            "steps": [
                {
                    "name": step.name,
                    "command": step.command,
                    "depends_on": list(step.depends_on),
                }
                for step in self.steps
            ],
            "matrix": {axis: list(values) for axis, values in self.matrix.items()},
            "metadata": dict(self.metadata),
            "template": self.template,
            "non_goals": list(self.non_goals),
            "verification_commands": [dict(command) for command in self.verification_commands],
            "risks": [dict(risk) for risk in self.risks],
            "artifacts": [dict(artifact) for artifact in self.artifacts],
            "owner": list(self.owner) if isinstance(self.owner, list) else self.owner,
            "agent_instructions": (
                dict(self.agent_instructions)
                if isinstance(self.agent_instructions, dict)
                else self.agent_instructions
            ),
            "spec_version": self.spec_version,
            "interview_mode": self.interview_mode,
            "clarity_score": dict(self.clarity_score),
            "assumptions": [dict(a) for a in self.assumptions],
            "premortem": self.premortem,
            "branches_explored": self.branches_explored,
            "concepts": [dict(c) for c in self.concepts],
        }


@dataclass(frozen=True)
class SpecGrade:
    """Static completeness grade assigned to a parsed spec."""

    grade: str
    criteria_met: int
    criteria_total: int
    details: dict[str, bool]

    def to_event_payload(self) -> dict[str, Any]:
        """Return a JSON-compatible grade payload."""
        return {
            "grade": self.grade,
            "criteria_met": self.criteria_met,
            "criteria_total": self.criteria_total,
            "details": dict(self.details),
        }


def assign_bronze_grade(spec: SeedSpec) -> SpecGrade:
    """Assign the Bronze grade for the minimal static spec criteria."""
    details = {
        "goal_present": bool(spec.goal.strip()),
        "constraints_present": len(spec.constraints) >= 1,
        "success_criteria_present": len(spec.success_criteria) >= 1,
        "yaml_parsed": True,
    }
    return SpecGrade(
        grade="bronze",
        criteria_met=sum(1 for passed in details.values() if passed),
        criteria_total=len(details),
        details=details,
    )


def load_seed_spec(path: Path) -> SeedSpec:
    """Load and validate a seed spec from JSON or the project YAML subset."""
    try:
        max_bytes = _configured_max_spec_bytes()
        size = path.stat().st_size
        if size > max_bytes:
            msg = f"seed spec validation failed: spec file exceeds {max_bytes} byte limit"
            raise SeedSpecValidationError(msg)
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read seed spec {path}: {exc.strerror or exc}"
        raise SeedSpecValidationError(msg) from exc

    try:
        values = _parse_mapping(raw)
    except (json.JSONDecodeError, SpecParseError, ValueError) as exc:
        msg = f"seed spec validation failed: {exc}"
        raise SeedSpecValidationError(msg) from exc

    return validate_seed_spec(values)


def validate_seed_spec(values: dict[str, Any]) -> SeedSpec:
    """Validate a decoded seed spec mapping."""
    errors: list[str] = []

    unknown = sorted(set(values) - ALLOWED_KEYS)
    if unknown:
        allowed = ", ".join(sorted(ALLOWED_KEYS))
        plural = "keys" if len(unknown) > 1 else "key"
        errors.append(
            f"unknown spec {plural}: {', '.join(repr(k) for k in unknown)}. "
            f"Allowed top-level keys: {allowed}."
        )

    project_type = _as_text(values.get("project_type", "greenfield")).lower()
    if project_type not in {"greenfield", "brownfield"}:
        errors.append("project_type must be either 'greenfield' or 'brownfield'")

    goal = _as_text(values.get("goal"))
    if not goal:
        errors.append("goal is required")

    constraints = _as_text_list(values.get("constraints"))
    if not constraints:
        errors.append("constraints must contain at least one item")

    success_criteria = _as_text_list(
        values.get("success_criteria", values.get("success")),
    )
    if not success_criteria:
        errors.append("success_criteria must contain at least one item")

    context = _as_text(values.get("context"))
    if project_type == "brownfield" and not context:
        errors.append("context is required for brownfield seed specs")

    steps_raw = values.get("steps")
    steps: list[SeedStep] = []
    if steps_raw is not None:
        try:
            steps = _normalize_steps(steps_raw)
        except ValueError as exc:
            errors.append(str(exc))

    matrix_raw = values.get("matrix")
    matrix: dict[str, list[str]] = {}
    if matrix_raw is not None:
        try:
            matrix = _normalize_matrix(matrix_raw)
        except ValueError as exc:
            errors.append(str(exc))

    metadata_raw = values.get("metadata")
    metadata: dict[str, str] = {}
    if metadata_raw is not None:
        try:
            metadata = _normalize_metadata(metadata_raw)
        except ValueError as exc:
            errors.append(str(exc))

    template = _as_text(values.get("template"))
    non_goals = _as_text_list(values.get("non_goals"))
    verification_commands: list[dict[str, Any]] = []
    if "verification_commands" in values:
        try:
            verification_commands = _normalize_mapping_list(
                values.get("verification_commands"), "verification_commands"
            )
        except ValueError as exc:
            errors.append(str(exc))

    risks: list[dict[str, Any]] = []
    if "risks" in values:
        try:
            risks = _normalize_mapping_list(values.get("risks"), "risks")
        except ValueError as exc:
            errors.append(str(exc))

    artifacts: list[dict[str, Any]] = []
    if "artifacts" in values:
        try:
            artifacts = _normalize_mapping_list(values.get("artifacts"), "artifacts")
        except ValueError as exc:
            errors.append(str(exc))

    owner: str | list[str] = ""
    if "owner" in values:
        try:
            owner = _normalize_owner(values.get("owner"))
        except ValueError as exc:
            errors.append(str(exc))

    agent_instructions: str | dict[str, str] = ""
    if "agent_instructions" in values:
        try:
            agent_instructions = _normalize_agent_instructions(values.get("agent_instructions"))
        except ValueError as exc:
            errors.append(str(exc))

    spec_version = 2
    if "spec_version" in values:
        try:
            spec_version = _as_int(values.get("spec_version"), "spec_version")
        except ValueError as exc:
            errors.append(str(exc))

    interview_mode = _as_text(values.get("interview_mode"))

    clarity_score_val: dict[str, str] = {}
    if "clarity_score" in values:
        try:
            clarity_score_val = _normalize_metadata(values.get("clarity_score"))
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

    if errors:
        raise SeedSpecValidationError("seed spec validation failed: " + "; ".join(errors))

    source_session_id = _as_optional_text(values.get("session_id"))
    return SeedSpec(
        source_session_id=source_session_id,
        project_type=project_type,
        goal=goal,
        constraints=constraints,
        success_criteria=success_criteria,
        context=context,
        steps=steps,
        matrix=matrix,
        metadata=metadata,
        template=template,
        non_goals=non_goals,
        verification_commands=verification_commands,
        risks=risks,
        artifacts=artifacts,
        owner=owner,
        agent_instructions=agent_instructions,
        spec_version=spec_version,
        interview_mode=interview_mode,
        clarity_score=clarity_score_val,
        assumptions=assumptions_val,
        premortem=premortem_val,
        branches_explored=branches_explored_val,
        concepts=concepts_val,
    )


def _normalize_steps(value: object) -> list[SeedStep]:
    if not isinstance(value, list):
        msg = "'steps' must be a list of step entries"
        raise ValueError(msg)
    steps: list[SeedStep] = []
    seen_names: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if isinstance(raw, str):
            name = raw.strip()
            if not name:
                msg = f"steps[{index}] is empty"
                raise ValueError(msg)
            command = ""
            depends: tuple[str, ...] = ()
        elif isinstance(raw, dict):
            name = _as_text(raw.get("name"))
            if not name:
                msg = f"steps[{index}] requires a 'name'"
                raise ValueError(msg)
            command = _as_text(raw.get("command"))
            depends_raw = raw.get("depends_on", [])
            depends_list = _as_text_list(depends_raw)
            depends = tuple(depends_list)
        else:
            msg = f"steps[{index}] must be a string or mapping with 'name'"
            raise ValueError(msg)
        if name in seen_names:
            msg = f"duplicate step name {name!r}"
            raise ValueError(msg)
        seen_names.add(name)
        steps.append(SeedStep(name=name, command=command, depends_on=depends))
    # Validate depends_on references.
    for step in steps:
        for dep in step.depends_on:
            if dep not in seen_names:
                msg = f"step {step.name!r} depends_on {dep!r} which is not declared"
                raise ValueError(msg)
    return steps


def _normalize_matrix(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        msg = "'matrix' must be a mapping of axis -> [values]"
        raise ValueError(msg)
    matrix: dict[str, list[str]] = {}
    for axis, raw in value.items():
        axis_name = _as_text(axis)
        if not axis_name:
            msg = "matrix axis name cannot be empty"
            raise ValueError(msg)
        values = _as_text_list(raw)
        if not values:
            msg = f"matrix axis {axis_name!r} requires at least one value"
            raise ValueError(msg)
        matrix[axis_name] = values
    return matrix


def _normalize_metadata(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        msg = "'metadata' must be a mapping of string keys to scalar values"
        raise ValueError(msg)
    metadata: dict[str, str] = {}
    for key, raw in value.items():
        key_name = _as_text(key)
        if not key_name:
            msg = "metadata key cannot be empty"
            raise ValueError(msg)
        metadata[key_name] = _as_text(raw)
    return metadata


def _normalize_mapping_list(value: object, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        msg = f"'{field_name}' must be a list of mappings"
        raise ValueError(msg)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            msg = f"{field_name}[{index}] must be a mapping"
            raise ValueError(msg)
        entry: dict[str, Any] = {}
        for raw_key, raw_value in item.items():
            key = _as_text(raw_key)
            if not key:
                msg = f"{field_name}[{index}] contains an empty key"
                raise ValueError(msg)
            entry[key] = _normalize_scalar_value(raw_value)
        normalized.append(entry)
    return normalized


def _normalize_owner(value: object) -> str | list[str]:
    if isinstance(value, list):
        owners = _as_text_list(value)
        if not owners:
            msg = "'owner' list must contain at least one item"
            raise ValueError(msg)
        return owners
    if isinstance(value, dict):
        msg = "'owner' must be a string or list of strings"
        raise ValueError(msg)
    return _as_text(value)


def _normalize_agent_instructions(value: object) -> str | dict[str, str]:
    if isinstance(value, dict):
        instructions: dict[str, str] = {}
        for key, raw in value.items():
            name = _as_text(key)
            if not name:
                msg = "'agent_instructions' mapping contains an empty key"
                raise ValueError(msg)
            instructions[name] = _as_text(raw)
        return instructions
    if isinstance(value, list):
        msg = "'agent_instructions' must be a string or mapping"
        raise ValueError(msg)
    return _as_text(value)


def _normalize_scalar_value(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_scalar_value(raw) for key, raw in value.items()}
    if isinstance(value, list):
        return [_normalize_scalar_value(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _as_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        msg = f"'{field_name}' must be an integer"
        raise ValueError(msg)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        msg = f"'{field_name}' must be an integer"
        raise ValueError(msg) from exc


def _parse_mapping(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        msg = "spec file is empty"
        raise SpecParseError(msg)
    if len(raw.encode("utf-8")) > _configured_max_spec_bytes():
        msg = f"spec file exceeds {_configured_max_spec_bytes()} byte limit"
        raise SpecParseError(msg)
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SpecParseError(str(exc)) from exc
        if not isinstance(parsed, dict):
            msg = "spec JSON must contain an object"
            raise SpecParseError(msg)
        _ensure_nesting_depth(parsed, max_depth=_MAX_NESTING_DEPTH)
        return dict(parsed)
    parsed_yaml = _parse_simple_yaml(stripped)
    _ensure_nesting_depth(parsed_yaml, max_depth=_MAX_NESTING_DEPTH)
    return parsed_yaml


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse the small YAML subset Mobius accepts.

    Supports:

    * Top-level ``key: value`` scalar pairs.
    * Top-level ``key:`` followed by indented ``-`` list items.
    * Top-level ``key:`` followed by indented ``subkey: value`` pairs (mappings).
    * Mapping subkeys may themselves have indented list values:

      .. code-block:: yaml

          matrix:
            platform:
              - ios
              - android

    * List items may be mappings (``- name: foo`` then indented
      ``  command: bar``) for the ``steps`` field, including nested
      ``depends_on`` lists.
    """
    return _YamlState(raw).parse()


class _YamlState:
    """Helper class for the simple-YAML parser.

    Encapsulates the small amount of mutable state needed so the logic stays
    readable. Public surface is just :meth:`parse`.
    """

    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.result: dict[str, Any] = {}
        self.current_key: str | None = None
        self.container_kind: str | None = None  # "list" | "mapping" | None
        # Active mapping subkey under current_key (for nested lists/mappings).
        self.active_subkey: str | None = None
        # Pending list-of-mappings item (for steps).
        self.pending_item: dict[str, Any] | None = None
        self.pending_item_indent: int | None = None
        # Pending nested list under a step field (e.g. ``depends_on``).
        self.pending_step_list_key: str | None = None
        self.seen_document_separator = False

    def parse(self) -> dict[str, Any]:
        for line_number, raw_line in enumerate(self.raw.splitlines(), start=1):
            self._handle_line(raw_line, line_number)
        self._flush_pending_item()
        for key, value in list(self.result.items()):
            if value is None:
                self.result[key] = []
        return self.result

    def _handle_line(self, raw_line: str, line_number: int = 1) -> None:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return
        self._reject_unsupported_features(stripped, line_number)
        if stripped == "---":
            if self.seen_document_separator or self.result or self.current_key is not None:
                raise SpecParseError(f"feature non supportée : multi-doc, ligne {line_number}")
            self.seen_document_separator = True
            return
        indent = len(line) - len(line.lstrip(" "))
        self._enforce_depth(indent, line_number)
        if indent == 0:
            self._handle_top_level(line, stripped)
            return
        self._handle_indented(line, stripped, indent)

    def _reject_unsupported_features(self, stripped: str, line_number: int) -> None:
        if "!!" in stripped:
            raise SpecParseError(f"feature non supportée : tag, ligne {line_number}")
        if _ANCHOR_RE.search(stripped):
            raise SpecParseError(f"feature non supportée : anchor, ligne {line_number}")
        if _REFERENCE_RE.search(stripped):
            raise SpecParseError(f"feature non supportée : reference, ligne {line_number}")
        if ":" in stripped:
            value_text = stripped.split(":", 1)[1].strip()
            if value_text in {"|", ">"} or value_text.startswith(("|", ">")):
                raise SpecParseError(f"feature non supportée : scalar block, ligne {line_number}")

    def _enforce_depth(self, indent: int, line_number: int) -> None:
        depth = indent // 2 + 1
        if depth > _MAX_NESTING_DEPTH:
            raise SpecParseError(
                f"nesting depth exceeds {_MAX_NESTING_DEPTH} level limit, ligne {line_number}"
            )

    def _handle_top_level(self, line: str, stripped: str) -> None:
        self._flush_pending_item()
        self.active_subkey = None
        if stripped.startswith("- "):
            msg = f"list item without preceding key: {line}"
            raise SpecParseError(msg)
        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise SpecParseError(msg)
        key, value = stripped.split(":", 1)
        self.current_key = key.strip()
        self.container_kind = None
        value_text = value.strip()
        if value_text == "":
            self.result[self.current_key] = None
        else:
            self.result[self.current_key] = _strip_quotes(value_text)

    def _handle_indented(self, line: str, stripped: str, indent: int) -> None:
        if self.current_key is None:
            msg = f"unexpected indented line without a parent key: {line}"
            raise SpecParseError(msg)

        # Inside a list-of-mappings item (steps): items deeper than the
        # mapping's leading indent belong to the pending item.
        if (
            self.pending_item is not None
            and self.pending_item_indent is not None
            and indent > self.pending_item_indent
        ):
            self._handle_pending_item_continuation(line, stripped, indent)
            return

        if stripped.startswith("- "):
            self._handle_list_item(stripped, indent)
            return

        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise SpecParseError(msg)
        sub_key_raw, sub_value_raw = stripped.split(":", 1)
        sub_key = sub_key_raw.strip()
        sub_value = sub_value_raw.strip()
        self._handle_mapping_entry(sub_key, sub_value, line)

    def _handle_pending_item_continuation(self, line: str, stripped: str, indent: int) -> None:
        assert self.pending_item is not None  # for type checkers
        if stripped.startswith("- "):
            # Nested list inside a mapping field of a step.
            if self.pending_step_list_key is None:
                msg = f"unexpected list item inside step: {line}"
                raise SpecParseError(msg)
            target = self.pending_item.setdefault(self.pending_step_list_key, [])
            if not isinstance(target, list):
                msg = f"step field {self.pending_step_list_key!r} cannot mix scalar and list values"
                raise SpecParseError(msg)
            target.append(_strip_quotes(stripped[2:].strip()))
            return
        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise SpecParseError(msg)
        k, v = stripped.split(":", 1)
        sub_key = k.strip()
        sub_value = v.strip()
        if sub_value == "":
            self.pending_item[sub_key] = []
            self.pending_step_list_key = sub_key
        else:
            self.pending_item[sub_key] = _strip_quotes(sub_value)
            self.pending_step_list_key = None

    def _handle_list_item(self, stripped: str, indent: int) -> None:
        item_text = stripped[2:].strip()
        # If a mapping subkey is active and this list item is indented deeper,
        # the items go under the subkey (e.g. matrix.platform: [ios, android]).
        if self.active_subkey is not None and self.container_kind == "mapping":
            assert self.current_key is not None
            mapping = self.result[self.current_key]
            if not isinstance(mapping, dict):
                msg = f"key {self.current_key!r} expected to be a mapping"
                raise SpecParseError(msg)
            target_list = mapping.setdefault(self.active_subkey, [])
            if not isinstance(target_list, list):
                msg = (
                    f"key {self.current_key!r}.{self.active_subkey!r} cannot mix scalar "
                    "and list values"
                )
                raise SpecParseError(msg)
            target_list.append(_strip_quotes(item_text))
            return

        # Normal top-level list under current_key.
        assert self.current_key is not None
        if self.container_kind is None or self.result.get(self.current_key) is None:
            self.result[self.current_key] = []
            self.container_kind = "list"
        elif self.container_kind != "list":
            msg = (
                f"key {self.current_key!r} mixes list items with mapping or scalar values; "
                "use either '- items' or 'subkey: value' indentation, not both"
            )
            raise SpecParseError(msg)
        assert self.current_key is not None
        target_list = self.result[self.current_key]
        if not isinstance(target_list, list):
            msg = (
                f"key {self.current_key!r} mixes list items with mapping or scalar values; "
                "use either '- items' or 'subkey: value' indentation, not both"
            )
            raise SpecParseError(msg)
        self._flush_pending_item_into(target_list)
        if ":" in item_text and not item_text.startswith(("'", '"')):
            k, v = item_text.split(":", 1)
            self.pending_item = {k.strip(): _strip_quotes(v.strip())}
            self.pending_item_indent = indent
            self.pending_step_list_key = None
        else:
            target_list.append(_strip_quotes(item_text))

    def _handle_mapping_entry(self, sub_key: str, sub_value: str, line: str) -> None:
        assert self.current_key is not None
        if self.container_kind is None or self.result.get(self.current_key) is None:
            self.result[self.current_key] = {}
            self.container_kind = "mapping"
        elif self.container_kind != "mapping":
            msg = (
                f"key {self.current_key!r} mixes mapping entries with list or scalar values; "
                "use either 'subkey: value' or '- items' indentation, not both"
            )
            raise SpecParseError(msg)
        target_map = self.result[self.current_key]
        if not isinstance(target_map, dict):
            msg = (
                f"key {self.current_key!r} mixes mapping entries with list or scalar values; "
                "use either 'subkey: value' or '- items' indentation, not both"
            )
            raise SpecParseError(msg)
        if sub_value == "":
            target_map[sub_key] = []
            self.active_subkey = sub_key
        else:
            target_map[sub_key] = _strip_quotes(sub_value)
            self.active_subkey = None
        # quench unused-variable lint
        _ = line

    def _flush_pending_item(self) -> None:
        if self.pending_item is not None and self.current_key is not None:
            target = self.result.setdefault(self.current_key, [])
            if isinstance(target, list):
                target.append(self.pending_item)
            self.pending_item = None
            self.pending_item_indent = None
            self.pending_step_list_key = None

    def _flush_pending_item_into(self, target_list: list[Any]) -> None:
        if self.pending_item is not None:
            target_list.append(self.pending_item)
            self.pending_item = None
            self.pending_item_indent = None
            self.pending_step_list_key = None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _as_optional_text(value: object) -> str | None:
    text = _as_text(value)
    return text or None


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return ""
    return str(value).strip()


def _as_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _as_text(value)
    return [text] if text else []


def _configured_max_spec_bytes() -> int:
    home = os.environ.get("MOBIUS_HOME")
    if not home:
        return _DEFAULT_MAX_SPEC_BYTES
    config_path = Path(home).expanduser() / "config.json"
    if not config_path.exists():
        return _DEFAULT_MAX_SPEC_BYTES
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _DEFAULT_MAX_SPEC_BYTES
    if not isinstance(raw, dict):
        return _DEFAULT_MAX_SPEC_BYTES
    value = raw.get("spec_max_bytes", raw.get("max_spec_bytes", _DEFAULT_MAX_SPEC_BYTES))
    try:
        configured = int(str(value))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SPEC_BYTES
    return configured if configured > 0 else _DEFAULT_MAX_SPEC_BYTES


def _ensure_nesting_depth(value: object, *, max_depth: int) -> None:
    def walk(node: object, depth: int) -> None:
        if isinstance(node, dict):
            if depth > max_depth:
                msg = f"nesting depth exceeds {max_depth} level limit"
                raise SpecParseError(msg)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            if depth > max_depth:
                msg = f"nesting depth exceeds {max_depth} level limit"
                raise SpecParseError(msg)
            for child in node:
                walk(child, depth + 1)

    walk(value, 1)
