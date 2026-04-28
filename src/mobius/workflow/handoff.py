"""Render versioned agent handoff prompts from a Mobius spec."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from mobius.agents import KNOWN_AGENTS, TEMPLATE_VERSION
from mobius.persistence.event_store import EventStore
from mobius.workflow.qa import Verdict
from mobius.workflow.seed import SeedSpec, SeedSpecValidationError, load_seed_spec


@dataclass(frozen=True)
class RenderedHandoff:
    """A rendered handoff prompt and its event payload."""

    agent: str
    prompt: str
    template_version: int
    criteria_count: int

    def event_payload(self, *, dry_run: bool) -> dict[str, Any]:
        """Return the ``handoff.generated`` event payload."""
        return {
            "agent": self.agent,
            "template_version": self.template_version,
            "criteria_count": self.criteria_count,
            "dry_run": dry_run,
        }


def generate_handoff(
    *,
    event_store_path: Path,
    spec_path: Path,
    agent: str,
    dry_run: bool,
) -> RenderedHandoff:
    """Render a prompt for ``agent`` and emit a versioned handoff event."""
    spec = load_seed_spec(spec_path)
    rendered = render_handoff(spec, agent=agent)
    with EventStore(event_store_path) as store:
        store.append_event(
            _handoff_aggregate_id(spec_path),
            "handoff.generated",
            rendered.event_payload(dry_run=dry_run),
        )
    return rendered


def render_handoff(spec: SeedSpec, *, agent: str) -> RenderedHandoff:
    """Render a handoff prompt for one known agent."""
    if agent not in KNOWN_AGENTS:
        msg = f"unknown handoff agent {agent!r}; known agents: {', '.join(KNOWN_AGENTS)}"
        raise ValueError(msg)
    template = Template(_load_template(agent))
    prompt = template.safe_substitute(
        goal=spec.goal,
        criteria=_format_criteria(spec),
        commands=_format_commands(spec.verification_commands),
        risks=_format_risks(spec.risks),
        instructions_section=_format_instructions_section(spec.agent_instructions),
    )
    return RenderedHandoff(
        agent=agent,
        prompt=prompt.rstrip() + "\n",
        template_version=TEMPLATE_VERSION,
        criteria_count=len(spec.success_criteria),
    )


def _load_template(agent: str) -> str:
    template_name = f"{agent}.j2.md"
    try:
        return (
            resources.files("mobius.agents.templates")
            .joinpath(template_name)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        msg = f"missing handoff template for agent {agent!r}: {template_name}"
        raise ValueError(msg) from exc


def _format_criteria(spec: SeedSpec) -> str:
    if not spec.success_criteria:
        return "- (none)"
    lines: list[str] = []
    for index, criterion in enumerate(spec.success_criteria, start=1):
        commands = [
            command
            for command in spec.verification_commands
            if _command_matches_criterion(command, _criterion_reference_keys(criterion, index))
        ]
        verdict = Verdict.UNVERIFIED.value if not commands else Verdict.PASS.value
        command_text = "; ".join(_command_text(command) for command in commands) or "no command"
        lines.append(f"- verdict={verdict} {criterion} — command: {command_text}")
    return "\n".join(lines)


def _format_commands(commands: list[dict[str, Any]]) -> str:
    if not commands:
        return "- (none)"
    lines: list[str] = []
    for index, command in enumerate(commands, start=1):
        ref = command.get(
            "criterion_ref",
            command.get("criterion_refs", command.get("criteria", "")),
        )
        timeout = command.get("timeout_s")
        suffix = f" (criterion_ref: {_jsonish(ref)})" if ref else ""
        if timeout is not None:
            suffix = f"{suffix} timeout_s={timeout}"
        lines.append(f"- {index}. `{_command_text(command)}`{suffix}")
    return "\n".join(lines)


def _format_risks(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return "- (none)"
    return "\n".join(f"- {_format_mapping(risk)}" for risk in risks)


def _format_instructions_section(instructions: str | dict[str, str]) -> str:
    if isinstance(instructions, dict):
        filtered = {key: value for key, value in instructions.items() if value}
        if not filtered:
            return ""
        body = "\n".join(f"- {key}: {value}" for key, value in sorted(filtered.items()))
    elif instructions.strip():
        body = instructions.strip()
    else:
        return ""
    return f"\n## <INSTRUCTIONS>\n{body}\n"


def _format_mapping(values: dict[str, Any]) -> str:
    if not values:
        return "(empty)"
    return ", ".join(f"{key}: {_jsonish(value)}" for key, value in sorted(values.items()))


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _command_text(command: dict[str, Any]) -> str:
    value = command.get("command", "")
    return str(value).strip()


def _command_matches_criterion(command: dict[str, Any], references: set[str]) -> bool:
    raw_ref = command.get("criterion_ref")
    if raw_ref is None:
        raw_ref = command.get("criterion_refs")
    if raw_ref is None:
        raw_ref = command.get("criteria")
    if isinstance(raw_ref, list):
        return any(_normalize_ref(item) in references for item in raw_ref)
    return _normalize_ref(raw_ref) in references


def _criterion_reference_keys(criterion: str, index: int) -> set[str]:
    stripped = criterion.strip()
    keys = {
        str(index),
        f"criterion-{index}",
        f"criterion_{index}",
        f"C{index}",
        f"c{index}",
        stripped,
    }
    first_token = stripped.split(maxsplit=1)[0] if stripped else ""
    if first_token:
        keys.add(first_token.rstrip(":.-—"))
    return {_normalize_ref(key) for key in keys if key}


def _normalize_ref(value: object) -> str:
    return " ".join(str(value).strip().split()).lower()


def _handoff_aggregate_id(spec_path: Path) -> str:
    try:
        resolved = spec_path.expanduser().resolve()
    except OSError as exc:
        msg = f"cannot resolve spec path for handoff: {exc}"
        raise SeedSpecValidationError(msg) from exc
    return f"handoff:{resolved}"
