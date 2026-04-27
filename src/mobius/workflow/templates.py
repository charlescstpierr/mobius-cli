"""Project-type templates for ``mobius init`` and ``mobius interview``.

Mobius does not run any of the commands described below — it only stores
acceptance criteria and emits events. The templates seed sensible defaults
so each project type starts with criteria that match what an agent or CI
wrapper would actually verify.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Templates known to Mobius. Order matters for help output.
TEMPLATE_NAMES: tuple[str, ...] = ("web", "cli", "lib", "etl", "mobile", "docs", "blank")


@dataclass(frozen=True)
class ProjectTemplate:
    """Scaffolded defaults for one project type."""

    name: str
    description: str
    goal: str
    constraints: tuple[str, ...]
    success_criteria: tuple[str, ...]
    steps: tuple[tuple[str, str], ...] = ()  # (name, command)
    matrix: tuple[tuple[str, tuple[str, ...]], ...] = ()


_TEMPLATES: dict[str, ProjectTemplate] = {
    "web": ProjectTemplate(
        name="web",
        description="Web app pipeline: lint, typecheck, build, e2e, deploy.",
        goal="Ship a web app preview deploy with passing lint, typecheck, build, and e2e tests.",
        constraints=(
            "All scripts must exit 0",
            "Preview URL must be reachable",
        ),
        success_criteria=(
            "lint passes (npm run lint)",
            "typecheck passes (npm run typecheck)",
            "build succeeds (npm run build)",
            "e2e tests pass (npm run e2e)",
            "preview deploy URL emitted",
        ),
        steps=(
            ("lint", "npm run lint"),
            ("typecheck", "npm run typecheck"),
            ("build", "npm run build"),
            ("e2e", "npm run e2e"),
            ("deploy", "npm run deploy:preview"),
        ),
    ),
    "cli": ProjectTemplate(
        name="cli",
        description="CLI tool release: format, lint, test, build, ship.",
        goal="Release a CLI binary with formatted, lint-clean, tested, and built artifacts.",
        constraints=(
            "Toolchain pinned and reproducible",
            "Release artifact must be a single self-contained binary",
        ),
        success_criteria=(
            "fmt check passes",
            "lint passes with warnings as errors",
            "unit tests pass",
            "release build produces the binary",
            "release artifact uploaded",
        ),
        steps=(
            ("fmt", "make fmt-check"),
            ("lint", "make lint"),
            ("test", "make test"),
            ("build", "make release"),
            ("release", "make publish"),
        ),
    ),
    "lib": ProjectTemplate(
        name="lib",
        description="Library publish (PyPI/npm/crates.io): quality gates + dual artifacts.",
        goal="Publish a library to its registry with quality gates and dual-format artifacts.",
        constraints=(
            "Strict typing required",
            "Distribution metadata must validate before upload",
        ),
        success_criteria=(
            "linter passes on src/ and tests/",
            "type checker passes on src/",
            "test suite passes with required coverage",
            "package builder produces sdist + wheel",
            "metadata validation passes",
        ),
        steps=(
            ("lint", "make lint"),
            ("typecheck", "make typecheck"),
            ("test", "make test"),
            ("build", "make build"),
            ("publish", "make publish"),
        ),
    ),
    "etl": ProjectTemplate(
        name="etl",
        description="ETL pipeline: extract, transform, load, validate (with stage ordering).",
        goal="Run nightly ETL pipeline producing validated load artifacts.",
        constraints=(
            "Each stage writes its intermediate artifact under data/",
            "Stages run sequentially; downstream depends on upstream",
            "Total runtime budget 30 minutes",
        ),
        success_criteria=(
            "extract stage produces data/raw.json",
            "transform stage produces data/clean.json",
            "load stage produces data/loaded.json",
            "validate stage produces data/validation.txt",
        ),
        steps=(
            ("extract", "./extract.sh"),
            ("transform", "./transform.sh"),
            ("load", "./load.sh"),
            ("validate", "./validate.sh"),
        ),
    ),
    "mobile": ProjectTemplate(
        name="mobile",
        description="Mobile app: iOS + Android matrix release.",
        goal="Ship a mobile app to internal track on iOS and Android.",
        constraints=(
            "Both platforms must build cleanly",
            "Internal track upload required for each platform",
        ),
        success_criteria=(
            "dependencies fetched",
            "static analysis passes (no errors)",
            "test suite passes",
            "Android APK built",
            "iOS IPA built",
            "Android uploaded to internal track",
            "iOS uploaded to internal track",
        ),
        matrix=(("platform", ("ios", "android")),),
        steps=(
            ("deps", "make deps"),
            ("analyze", "make analyze"),
            ("test", "make test"),
            ("build_android", "make build-android"),
            ("build_ios", "make build-ios"),
            ("upload_android", "make upload-android"),
            ("upload_ios", "make upload-ios"),
        ),
    ),
    "docs": ProjectTemplate(
        name="docs",
        description="Markdown docs site: spell-check, link-check, build, deploy.",
        goal="Build and deploy versioned product documentation site.",
        constraints=(
            "Markdown sources under docs/",
            "All internal links must resolve",
        ),
        success_criteria=(
            "spell check finds no errors",
            "link check passes",
            "diagram render passes",
            "site builds (output produced)",
            "preview deployed",
        ),
        steps=(
            ("spell", "make spell"),
            ("links", "make links"),
            ("diagrams", "make diagrams"),
            ("build", "make build"),
            ("deploy", "make deploy"),
        ),
    ),
    "blank": ProjectTemplate(
        name="blank",
        description="Blank starter — replace placeholders before running.",
        goal="Describe what you want Mobius to track for you.",
        constraints=("Replace this constraint with a real one.",),
        success_criteria=("Replace this criterion with something testable.",),
    ),
}


def get_template(name: str) -> ProjectTemplate:
    """Return the named template or the blank fallback."""
    key = name.strip().lower() if name else "blank"
    return _TEMPLATES.get(key, _TEMPLATES["blank"])


def detect_template(workspace: Path) -> str:
    """Auto-detect a template from the workspace's manifests.

    Returns one of the names in :data:`TEMPLATE_NAMES`. Falls back to ``blank``
    when no recognisable manifest is present.
    """
    workspace = workspace.expanduser()
    if not workspace.exists():
        return "blank"
    # Mobile beats web/lib because Flutter projects also have a Dart pubspec.
    has_pubspec = (workspace / "pubspec.yaml").exists()
    has_native_dirs = (workspace / "ios").is_dir() and (workspace / "android").is_dir()
    if has_pubspec or has_native_dirs:
        return "mobile"
    if (workspace / "mkdocs.yml").exists() or (workspace / "docs" / "index.md").exists():
        return "docs"
    if (workspace / "pyproject.toml").exists():
        return "lib"
    if (workspace / "Cargo.toml").exists():
        return "cli"
    if (workspace / "package.json").exists():
        return "web"
    if (workspace / "dbt_project.yml").exists() or (workspace / "airflow.cfg").exists():
        return "etl"
    return "blank"


def render_spec(template: ProjectTemplate, *, project_type: str = "greenfield") -> str:
    """Render a YAML spec file for the given template."""
    lines: list[str] = [
        f"# Mobius spec — generated from template '{template.name}'",
        f"# {template.description}",
        f"project_type: {project_type}",
        f"template: {template.name}",
        f"goal: {_yaml_scalar(template.goal)}",
        "constraints:",
    ]
    lines.extend(_yaml_list(template.constraints))
    lines.append("success_criteria:")
    lines.extend(_yaml_list(template.success_criteria))
    if template.steps:
        lines.append("steps:")
        for name, command in template.steps:
            lines.append(f"  - name: {_yaml_scalar(name)}")
            if command:
                lines.append(f"    command: {_yaml_scalar(command)}")
    if template.matrix:
        lines.append("matrix:")
        for axis, values in template.matrix:
            lines.append(f"  {axis}:")
            for value in values:
                lines.append(f"    - {_yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    special = any(ch in value for ch in ":#[]{}&*!|>'\"%@`")
    if special or value != value.strip() or "\n" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _yaml_list(values: tuple[str, ...] | list[str]) -> list[str]:
    if not values:
        return ["  []"]
    return [f"  - {_yaml_scalar(v)}" for v in values]
