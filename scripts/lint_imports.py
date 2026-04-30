#!/usr/bin/env python3
"""AST-based import lints for Mobius.

These checks intentionally live outside pytest so pre-commit and CI can run
them before the test suite starts. They inspect only top-level imports because
lazy imports inside functions are allowed and sometimes required for cold-start
performance.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V3A_ROOT = REPO_ROOT / "src" / "mobius" / "v3a"
BANNED_V3A_TOP_LEVEL_IMPORTS = frozenset({"subprocess", "sqlite3", "rich.live"})


@dataclass(frozen=True)
class ImportViolation:
    path: Path
    line: int
    import_name: str

    def format(self, *, repo_root: Path) -> str:
        try:
            display_path = self.path.relative_to(repo_root)
        except ValueError:
            display_path = self.path
        return (
            f"{display_path}:{self.line}: top-level import '{self.import_name}' is banned; "
            "move it inside the function that needs it"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint Mobius source files for banned imports.")
    parser.add_argument(
        "--check",
        action="append",
        type=Path,
        dest="checks",
        help="Specific Python file to check. May be passed multiple times.",
    )
    args = parser.parse_args(argv)

    files = tuple(_selected_files(args.checks))
    violations = lint_files(files)
    if not violations:
        return 0

    print("Import lint failed:", file=sys.stderr)
    for violation in violations:
        print(f"  - {violation.format(repo_root=REPO_ROOT)}", file=sys.stderr)
    return 1


def lint_files(files: Iterable[Path]) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    for path in files:
        resolved = path.expanduser().resolve()
        tree = ast.parse(resolved.read_text(encoding="utf-8"), filename=str(resolved))
        violations.extend(_lint_top_level_imports(resolved, tree))
    return violations


def _selected_files(checks: Sequence[Path] | None) -> Iterable[Path]:
    if checks:
        return checks
    return sorted(V3A_ROOT.rglob("*.py"))


def _lint_top_level_imports(path: Path, tree: ast.Module) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    for node in tree.body:
        for import_name in _top_level_imports(node):
            if import_name in BANNED_V3A_TOP_LEVEL_IMPORTS:
                violations.append(
                    ImportViolation(path=path, line=node.lineno, import_name=import_name)
                )
    return violations


def _top_level_imports(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return {node.module}
    return set()


if __name__ == "__main__":
    raise SystemExit(main())
