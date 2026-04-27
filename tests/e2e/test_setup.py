import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SKILLS = {
    "cancel",
    "evolve",
    "help",
    "interview",
    "run",
    "seed",
    "setup",
    "status",
    "qa",
    "ac-tree",
    "lineage",
}


def run_mobius(*args: str, home: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MOBIUS_TEST_HOME"] = str(home)
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=cwd or PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def installed_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_setup_help_documents_required_flags(tmp_path: Path) -> None:
    result = run_mobius("setup", "--help", home=tmp_path)

    assert result.returncode == 0
    assert "--runtime" in result.stdout
    assert "--scope" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--uninstall" in result.stdout


def test_dry_run_prints_plan_without_writing_files(tmp_path: Path) -> None:
    result = run_mobius("setup", "--runtime", "claude", "--dry-run", home=tmp_path)

    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "would install:" in result.stdout
    assert list(tmp_path.rglob("*")) == []


def test_setup_claude_populates_skills_and_commands_idempotently(tmp_path: Path) -> None:
    first = run_mobius("setup", "--runtime", "claude", home=tmp_path)
    before = installed_hashes(tmp_path / ".claude")
    second = run_mobius("setup", "--runtime", "claude", home=tmp_path)
    after = installed_hashes(tmp_path / ".claude")

    assert first.returncode == 0
    assert second.returncode == 0
    assert before == after
    for skill_name in REQUIRED_SKILLS:
        assert (tmp_path / ".claude" / "skills" / skill_name / "SKILL.md").is_file()
        assert (tmp_path / ".claude" / "commands" / f"{skill_name}.md").is_file()
    assert "skip:" in second.stdout


def test_setup_codex_and_hermes_populate_skills(tmp_path: Path) -> None:
    for runtime in ("codex", "hermes"):
        result = run_mobius("setup", "--runtime", runtime, home=tmp_path)

        assert result.returncode == 0
        for skill_name in REQUIRED_SKILLS:
            assert (tmp_path / f".{runtime}" / "skills" / skill_name / "SKILL.md").is_file()


def test_project_scope_installs_under_current_working_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()

    result = run_mobius(
        "setup",
        "--runtime",
        "claude",
        "--scope",
        "project",
        home=home,
        cwd=project,
    )

    assert result.returncode == 0
    assert (project / ".claude" / "skills" / "setup" / "SKILL.md").is_file()
    assert (project / ".claude" / "commands" / "setup.md").is_file()
    assert not (home / ".claude").exists()


def test_uninstall_removes_only_mobius_installed_assets(tmp_path: Path) -> None:
    setup = run_mobius("setup", "--runtime", "claude", home=tmp_path)
    keep_file = tmp_path / ".claude" / "skills" / "keep.md"
    modified_file = tmp_path / ".claude" / "skills" / "setup" / "SKILL.md"
    keep_file.write_text("user-owned\n", encoding="utf-8")
    modified_file.write_text("user modified\n", encoding="utf-8")

    uninstall = run_mobius("setup", "--runtime", "claude", "--uninstall", home=tmp_path)

    assert setup.returncode == 0
    assert uninstall.returncode == 0
    assert keep_file.read_text(encoding="utf-8") == "user-owned\n"
    assert modified_file.read_text(encoding="utf-8") == "user modified\n"
    assert not (tmp_path / ".claude" / "commands" / "run.md").exists()
    assert "skip modified:" in uninstall.stdout


def test_setup_never_edits_claude_json_mcp_servers(tmp_path: Path) -> None:
    claude_config = tmp_path / ".claude.json"
    before = {"mcpServers": {"existing": {"command": "do-not-touch"}}, "other": True}
    claude_config.write_text(json.dumps(before, sort_keys=True), encoding="utf-8")

    result = run_mobius("setup", "--runtime", "claude", home=tmp_path)

    assert result.returncode == 0
    after = json.loads(claude_config.read_text(encoding="utf-8"))
    assert after["mcpServers"] == before["mcpServers"]


def test_unknown_runtime_exits_nonzero_with_supported_runtimes(tmp_path: Path) -> None:
    result = run_mobius("setup", "--runtime", "unknown", home=tmp_path)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Supported runtimes: claude, codex, hermes" in result.stderr
