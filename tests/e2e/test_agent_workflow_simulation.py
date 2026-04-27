"""Simulate a coding agent driving Mobius end-to-end.

Each test impersonates an agent (Claude, Codex, Hermes) that:

1. Has had a conversation with the user.
2. Extracts goal / constraints / success criteria from that conversation.
3. Calls ``mobius interview --non-interactive`` with the extracted values.
4. Verifies the resulting ``spec.yaml`` contains exactly what the user said.

The same scenario runs for all three runtimes after their respective
``mobius setup`` install. The point is that the *recipe* is identical
across runtimes — Mobius itself is runtime-agnostic.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1].parent

# A realistic agent transcript. The agent has held this conversation, then
# extracts a structured payload that becomes the CLI invocation. We model
# only the extraction step (what flags the agent would compose).
USER_DESCRIPTION = (
    "I want to build a Next.js dashboard for tracking sales, with auth, "
    "deploys to Vercel, must hit Lighthouse 90+."
)

EXTRACTED = {
    "template": "web",
    "project_type": "greenfield",
    "goal": "Ship a Next.js sales dashboard with auth deployed to Vercel.",
    "constraints": [
        "Deploy target is Vercel",
        "Use NextAuth.js for authentication",
    ],
    "success_criteria": [
        "Lighthouse score >= 90 on the dashboard route",
        "Auth flow works end-to-end",
        "Vercel preview deploy succeeds",
    ],
}


def _run_mobius(
    *args: str, mobius_home: Path, cwd: Path
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MOBIUS_HOME": str(mobius_home),
        "MOBIUS_TEST_HOME": str(mobius_home),
        "NO_COLOR": "1",
    }
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _agent_invocation(workspace: Path, output_path: Path) -> list[str]:
    """Reproduce the exact flag sequence an agent would compose."""
    args: list[str] = [
        "interview",
        "--non-interactive",
        "--template",
        EXTRACTED["template"],
        "--project-type",
        EXTRACTED["project_type"],
        "--goal",
        EXTRACTED["goal"],
        "--output",
        str(output_path),
    ]
    for constraint in EXTRACTED["constraints"]:
        args.extend(["--constraint", constraint])
    for criterion in EXTRACTED["success_criteria"]:
        args.extend(["--success-criterion", criterion])
    return args


@pytest.mark.parametrize("runtime", ["claude", "codex", "hermes"])
def test_agent_drives_mobius_end_to_end(tmp_path: Path, runtime: str) -> None:
    """Simulate runtime install + agent-driven interview + spec inspection."""
    mobius_home = tmp_path / "mobius-home"
    workspace = tmp_path / f"workspace-{runtime}"
    workspace.mkdir()
    # The web template would normally pick up package.json — leave the
    # workspace empty so we exercise the explicit --template path.

    # 1. Install the runtime's Mobius assets.
    setup = _run_mobius("setup", "--runtime", runtime, mobius_home=mobius_home, cwd=workspace)
    assert setup.returncode == 0, setup.stderr

    # 2. Verify the runtime's interview asset tells the agent what to do.
    skill_path = mobius_home / f".{runtime}" / "skills" / "interview" / "SKILL.md"
    assert skill_path.is_file(), f"{runtime} did not receive an interview skill"
    skill = skill_path.read_text(encoding="utf-8")
    assert "Bash('mobius interview" in skill
    assert "--goal" in skill
    assert "--constraint" in skill
    assert "--success-criterion" in skill
    assert "MCP" in skill  # explicit "do not use MCP" guidance
    prompt_subdir = "prompts" if runtime == "codex" else "commands"
    prompt_path = mobius_home / f".{runtime}" / prompt_subdir / "interview.md"
    assert prompt_path.is_file(), f"{runtime} did not receive an interview prompt"

    # 3. Simulate the agent's CLI invocation after the conversation.
    spec = workspace / "spec.yaml"
    invocation = _agent_invocation(workspace, spec)
    result = _run_mobius(*invocation, mobius_home=mobius_home, cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("session_id=interview_")
    assert result.stderr == "", result.stderr

    # 4. Verify the spec contains the agent-extracted parameters verbatim.
    spec_text = spec.read_text(encoding="utf-8")
    assert f"goal: {EXTRACTED['goal']}" in spec_text
    assert "template: web" in spec_text
    assert "project_type: greenfield" in spec_text
    for constraint in EXTRACTED["constraints"]:
        assert constraint in spec_text
    for criterion in EXTRACTED["success_criteria"]:
        assert criterion in spec_text
    assert "ambiguity_score: 0.0" in spec_text


def test_agent_brownfield_invocation_includes_context(tmp_path: Path) -> None:
    """Brownfield scenario also surfaces context via --context."""
    mobius_home = tmp_path / "mobius-home"
    workspace = tmp_path / "brownfield-workspace"
    workspace.mkdir()

    # Pre-install setup for codex (simplest runtime to exercise) just so the
    # workspace state mirrors a real agent session.
    setup = _run_mobius("setup", "--runtime", "codex", mobius_home=mobius_home, cwd=workspace)
    assert setup.returncode == 0, setup.stderr

    spec = workspace / "spec.yaml"
    invocation = [
        "interview",
        "--non-interactive",
        "--template",
        "lib",
        "--project-type",
        "brownfield",
        "--goal",
        "Migrate the existing library to a v2 API without breaking consumers.",
        "--constraint",
        "Public API must remain backwards compatible.",
        "--constraint",
        "Coverage must stay >= 95%.",
        "--success-criterion",
        "All existing consumers continue to import without changes.",
        "--success-criterion",
        "New v2 surface ships behind a feature flag.",
        "--context",
        "Library has 3 years of consumers; semantic versioning is strict.",
        "--output",
        str(spec),
    ]
    result = _run_mobius(*invocation, mobius_home=mobius_home, cwd=workspace)
    assert result.returncode == 0, result.stderr

    spec_text = spec.read_text(encoding="utf-8")
    assert "project_type: brownfield" in spec_text
    assert "Library has 3 years of consumers" in spec_text
    assert "semantic versioning is strict" in spec_text


def test_agent_invocation_without_input_or_flags_exits_with_usage(tmp_path: Path) -> None:
    """Bare ``mobius interview --non-interactive`` is still a usage error."""
    mobius_home = tmp_path / "mobius-home"
    workspace = tmp_path / "no-flags"
    workspace.mkdir()
    result = _run_mobius(
        "interview", "--non-interactive", mobius_home=mobius_home, cwd=workspace
    )
    assert result.returncode == 2, result.stderr
    assert "--input" in result.stderr or "--goal" in result.stderr
