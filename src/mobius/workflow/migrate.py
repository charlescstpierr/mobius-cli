"""Spec migration helpers for Mobius."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SPEC_VERSION_2_RE = re.compile(r"(?m)^[ \t]*spec_version:[ \t]*2[ \t]*(?:#.*)?$")
_SPEC_VERSION_RE = re.compile(r"(?m)^[ \t]*spec_version:[^\n]*(?:\n|$)")
_TOP_LEVEL_KEY_RE_TEMPLATE = r"(?m)^(?![ \t]*#){key}:[^\n]*(?:\n|$)"

_PLACEHOLDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("non_goals", ("# non_goals:", "#   - <not-a-goal>")),
    (
        "verification_commands",
        (
            "# verification_commands:",
            "#   - command: <command>",
            "#     timeout_s: 60",
            "#     criterion_ref: <success-criterion-id>",
            "#     shell: true",
        ),
    ),
    (
        "risks",
        (
            "# risks:",
            "#   - description: <risk>",
            "#     severity: low",
            "#     mitigation: <mitigation>",
        ),
    ),
    (
        "artifacts",
        (
            "# artifacts:",
            "#   - name: <artifact>",
            "#     path: <path>",
            "#     type: <type>",
        ),
    ),
    ("owner", ("# owner: <owner>",)),
    ("agent_instructions", ("# agent_instructions: <instructions>",)),
)


@dataclass(frozen=True)
class MigrationResult:
    """Result of a spec migration attempt."""

    spec_path: Path
    backup_path: Path
    changed: bool
    backup_created: bool

    def to_payload(self) -> dict[str, str | bool]:
        """Return a JSON-compatible representation."""
        return {
            "spec_path": str(self.spec_path),
            "backup_path": str(self.backup_path),
            "changed": self.changed,
            "backup_created": self.backup_created,
        }


def migrate_spec(spec_path: Path) -> MigrationResult:
    """Upgrade a v1 spec file to v2 in place, preserving an original backup."""
    resolved_spec_path = spec_path.expanduser()
    raw = resolved_spec_path.read_text(encoding="utf-8")
    backup_path = resolved_spec_path.with_name(f"{resolved_spec_path.name}.v1.bak")

    if _SPEC_VERSION_2_RE.search(raw):
        return MigrationResult(
            spec_path=resolved_spec_path,
            backup_path=backup_path,
            changed=False,
            backup_created=False,
        )

    backup_created = False
    if not backup_path.exists():
        _atomic_write(backup_path, raw)
        backup_created = True

    migrated = _ensure_spec_version_2(raw)
    migrated = _append_missing_placeholders(migrated)
    _atomic_write(resolved_spec_path, migrated)

    return MigrationResult(
        spec_path=resolved_spec_path,
        backup_path=backup_path,
        changed=True,
        backup_created=backup_created,
    )


def _ensure_spec_version_2(raw: str) -> str:
    if _SPEC_VERSION_RE.search(raw):
        return _SPEC_VERSION_RE.sub("spec_version: 2\n", raw, count=1)
    return f"spec_version: 2\n{raw}"


def _append_missing_placeholders(raw: str) -> str:
    missing_blocks: list[str] = []
    for key, lines in _PLACEHOLDERS:
        key_pattern = _TOP_LEVEL_KEY_RE_TEMPLATE.format(key=re.escape(key))
        if not re.search(key_pattern, raw):
            missing_blocks.extend(lines)

    if not missing_blocks:
        return raw

    separator = "\n\n" if raw.endswith("\n") else "\n\n"
    suffix = "\n".join(missing_blocks)
    return f"{raw}{separator}{suffix}\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(content)
    temp_path.replace(path)
