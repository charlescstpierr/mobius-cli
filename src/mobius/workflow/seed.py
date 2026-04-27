"""Seed spec parsing and validation for the Mobius workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SeedSpecValidationError(ValueError):
    """Raised when a seed spec cannot be accepted."""


@dataclass(frozen=True)
class SeedSpec:
    """Validated input used to create a seed session."""

    source_session_id: str | None
    project_type: str
    goal: str
    constraints: list[str]
    success_criteria: list[str]
    context: str

    def to_event_payload(self) -> dict[str, Any]:
        """Return a JSON-compatible payload for event persistence."""
        return {
            "source_session_id": self.source_session_id,
            "project_type": self.project_type,
            "goal": self.goal,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
            "context": self.context,
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
    )


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
    result: dict[str, Any] = {}
    current_list_key: str | None = None
    current_mapping_key: str | None = None
    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if stripped.startswith("- "):
            if current_list_key is None:
                msg = f"list item without preceding key: {line}"
                raise ValueError(msg)
            cast_list = result.setdefault(current_list_key, [])
            if not isinstance(cast_list, list):
                msg = f"key {current_list_key!r} cannot contain both scalar and list values"
                raise ValueError(msg)
            cast_list.append(_strip_quotes(stripped[2:].strip()))
            continue
        if ":" not in stripped:
            msg = f"unsupported spec line: {line}"
            raise ValueError(msg)
        key, value = stripped.split(":", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        if indent > 0 and current_mapping_key is not None:
            existing = result.setdefault(current_mapping_key, {})
            if existing == []:
                existing = {}
                result[current_mapping_key] = existing
            if not isinstance(existing, dict):
                msg = f"key {current_mapping_key!r} cannot contain both scalar and mapping values"
                raise ValueError(msg)
            existing[normalized_key] = _strip_quotes(normalized_value)
            continue
        current_list_key = None
        current_mapping_key = None
        if normalized_value == "":
            result[normalized_key] = []
            current_list_key = normalized_key
            current_mapping_key = normalized_key
        else:
            result[normalized_key] = _strip_quotes(normalized_value)
    return result


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
