"""Seed spec parsing and validation for the Mobius workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
        # Interview-rendered fields kept for round-tripping.
        "ambiguity_score",
        "ambiguity_gate",
        "ambiguity_components",
    }
)


class SeedSpecValidationError(ValueError):
    """Raised when a seed spec cannot be accepted."""


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
        }


def load_seed_spec(path: Path) -> SeedSpec:
    """Load and validate a seed spec from JSON or the project YAML subset."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"cannot read seed spec {path}: {exc.strerror or exc}"
        raise SeedSpecValidationError(msg) from exc

    try:
        values = _parse_mapping(raw)
    except (json.JSONDecodeError, ValueError) as exc:
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


def _parse_mapping(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    if not stripped:
        msg = "spec file is empty"
        raise ValueError(msg)
    if stripped.startswith("{"):
        parsed = json.loads(stripped)
        if not isinstance(parsed, dict):
            msg = "spec JSON must contain an object"
            raise ValueError(msg)
        return dict(parsed)
    return _parse_simple_yaml(stripped)


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

    def parse(self) -> dict[str, Any]:
        for raw_line in self.raw.splitlines():
            self._handle_line(raw_line)
        self._flush_pending_item()
        for key, value in list(self.result.items()):
            if value is None:
                self.result[key] = []
        return self.result

    def _handle_line(self, raw_line: str) -> None:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            self._handle_top_level(line, stripped)
            return
        self._handle_indented(line, stripped, indent)

    def _handle_top_level(self, line: str, stripped: str) -> None:
        self._flush_pending_item()
        self.active_subkey = None
        if stripped.startswith("- "):
            msg = f"list item without preceding key: {line}"
            raise ValueError(msg)
        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise ValueError(msg)
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
            raise ValueError(msg)

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
            raise ValueError(msg)
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
                raise ValueError(msg)
            target = self.pending_item.setdefault(self.pending_step_list_key, [])
            if not isinstance(target, list):
                msg = f"step field {self.pending_step_list_key!r} cannot mix scalar and list values"
                raise ValueError(msg)
            target.append(_strip_quotes(stripped[2:].strip()))
            return
        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise ValueError(msg)
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
                raise ValueError(msg)
            target_list = mapping.setdefault(self.active_subkey, [])
            if not isinstance(target_list, list):
                msg = (
                    f"key {self.current_key!r}.{self.active_subkey!r} cannot mix scalar "
                    "and list values"
                )
                raise ValueError(msg)
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
            raise ValueError(msg)
        assert self.current_key is not None
        target_list = self.result[self.current_key]
        if not isinstance(target_list, list):
            msg = (
                f"key {self.current_key!r} mixes list items with mapping or scalar values; "
                "use either '- items' or 'subkey: value' indentation, not both"
            )
            raise ValueError(msg)
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
            raise ValueError(msg)
        target_map = self.result[self.current_key]
        if not isinstance(target_map, dict):
            msg = (
                f"key {self.current_key!r} mixes mapping entries with list or scalar values; "
                "use either 'subkey: value' or '- items' indentation, not both"
            )
            raise ValueError(msg)
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
