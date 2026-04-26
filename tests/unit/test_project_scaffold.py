import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_console_script_entry_point_declared() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"]["mobius"] == "mobius.cli:main"


def test_no_mcp_dependency_declared() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    dependencies = pyproject["project"].get("dependencies", [])

    assert all(not dependency.lower().startswith(("mcp", "mcp-sdk")) for dependency in dependencies)


def test_license_and_notice_present() -> None:
    assert (PROJECT_ROOT / "LICENSE").read_text().startswith("MIT License")

    notice = (PROJECT_ROOT / "NOTICE").read_text()
    assert "Q00/ouroboros" in notice


def test_source_package_has_no_mcp_imports() -> None:
    source_files = (PROJECT_ROOT / "src" / "mobius").rglob("*.py")
    disallowed_import = "import " + "mcp"
    disallowed_from_import = "from " + "mcp"

    for source_file in source_files:
        source = source_file.read_text()
        assert disallowed_import not in source
        assert disallowed_from_import not in source
