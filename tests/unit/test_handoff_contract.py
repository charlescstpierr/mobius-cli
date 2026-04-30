from __future__ import annotations

from pathlib import Path

from mobius.agents import KNOWN_AGENTS, TEMPLATE_VERSION
from mobius.workflow.handoff import render_handoff
from mobius.workflow.seed import load_seed_spec

HANDOFF_CONTRACT_SPEC = """
project_type: greenfield
goal: Ship a handoff prompt.
constraints:
  - Keep prompts deterministic.
success_criteria:
  - C1
  - C2
verification_commands:
  - command: "python -m pytest tests/unit/test_handoff_contract.py"
    criterion_ref: C1
  - command: "uv run ruff check src/ tests/"
    criterion_ref: C2
risks:
  - id: R1
    description: Template drift can hide required markers.
owner: qa-team
non_goals:
  - Do not install Jinja2.
agent_instructions:
  claude: Keep the summary concise.
  codex: Prefer exact commands.
""".strip()


def test_all_known_agents_have_markers(tmp_path: Path, spec_factory) -> None:
    spec_path = spec_factory(tmp_path / "spec.yaml", body=HANDOFF_CONTRACT_SPEC)
    spec = load_seed_spec(spec_path)

    for agent in KNOWN_AGENTS:
        rendered = render_handoff(spec, agent=agent)
        assert rendered.template_version == TEMPLATE_VERSION
        assert rendered.criteria_count == 2
        assert "<GOAL>" in rendered.prompt
        assert "<CRITERIA>" in rendered.prompt
        assert "<COMMANDS>" in rendered.prompt
        assert "<RISKS>" in rendered.prompt
        assert "<INSTRUCTIONS>" in rendered.prompt
        assert "Ship a handoff prompt." in rendered.prompt
        assert "python -m pytest" in rendered.prompt
        assert "Template drift" in rendered.prompt
