from pathlib import Path

from mobius.workflow.migrate import migrate_spec


def test_migrate_spec_upgrades_v1_and_preserves_original_backup(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    original = """goal: Ship v1
constraints:
  - Keep compatibility
success_criteria:
  - Migration succeeds
"""
    spec_path.write_text(original, encoding="utf-8")

    result = migrate_spec(spec_path)
    migrated = spec_path.read_text(encoding="utf-8")
    backup = tmp_path / "spec.yaml.v1.bak"

    assert result.changed is True
    assert result.backup_created is True
    assert backup.read_text(encoding="utf-8") == original
    assert migrated.startswith("spec_version: 2\n")
    assert "# non_goals:" in migrated
    assert "# verification_commands:" in migrated
    assert "# risks:" in migrated
    assert "# artifacts:" in migrated
    assert "# owner:" in migrated
    assert "# agent_instructions:" in migrated


def test_migrate_spec_is_idempotent_and_does_not_overwrite_backup(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    original = """goal: Ship v1
constraints:
  - Keep compatibility
success_criteria:
  - Migration succeeds
"""
    spec_path.write_text(original, encoding="utf-8")

    first = migrate_spec(spec_path)
    migrated_once = spec_path.read_text(encoding="utf-8")
    backup = tmp_path / "spec.yaml.v1.bak"
    backup.write_text("sentinel backup\n", encoding="utf-8")
    second = migrate_spec(spec_path)

    assert first.changed is True
    assert second.changed is False
    assert second.backup_created is False
    assert spec_path.read_text(encoding="utf-8") == migrated_once
    assert backup.read_text(encoding="utf-8") == "sentinel backup\n"


def test_migrate_spec_replaces_existing_non_v2_version(tmp_path: Path) -> None:
    spec_path = tmp_path / "custom.yaml"
    spec_path.write_text(
        """spec_version: 1
goal: Ship
constraints:
  - c
success_criteria:
  - s
owner: alice
""",
        encoding="utf-8",
    )

    result = migrate_spec(spec_path)
    migrated = spec_path.read_text(encoding="utf-8")

    assert result.changed is True
    assert migrated.startswith("spec_version: 2\n")
    assert "# owner:" not in migrated
