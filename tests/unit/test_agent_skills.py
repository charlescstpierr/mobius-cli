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


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    assert text.startswith("---\n")
    marker = "\n---\n"
    end = text.find(marker, 4)
    assert end != -1
    frontmatter_text = text[4:end]
    body = text[end + len(marker) :]
    frontmatter: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        key, separator, value = line.partition(":")
        assert separator == ":"
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def test_required_agent_skill_files_exist() -> None:
    for skill_name in REQUIRED_SKILLS:
        assert (PROJECT_ROOT / "skills" / skill_name / "SKILL.md").is_file()


def test_agent_skill_frontmatter_has_required_fields() -> None:
    for skill_name in REQUIRED_SKILLS:
        frontmatter, _body = parse_frontmatter(
            (PROJECT_ROOT / "skills" / skill_name / "SKILL.md").read_text()
        )

        assert frontmatter["name"] == skill_name
        assert frontmatter["description"]


def test_agent_skill_bodies_invoke_mobius_via_bash_without_mcp_tools() -> None:
    forbidden_tokens = ("mcp__", "mcp.")

    for skill_name in REQUIRED_SKILLS:
        _frontmatter, body = parse_frontmatter(
            (PROJECT_ROOT / "skills" / skill_name / "SKILL.md").read_text()
        )

        assert "Bash('" in body
        assert "mobius " in body
        assert all(token not in body for token in forbidden_tokens)
