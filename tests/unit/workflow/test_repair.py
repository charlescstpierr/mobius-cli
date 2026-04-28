import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow import repair as repair_module
from mobius.workflow.repair import RepairAction, run_repair


def _repair_event_count(home: Path, repair_type: str) -> int:
    with EventStore(home / "events.db") as store:
        return int(
            store.connection.execute(
                """
                SELECT count(*)
                FROM events
                WHERE type = 'doctor.repair_applied'
                  AND json_extract(payload, '$.repair_type') = ?
                """,
                (repair_type,),
            ).fetchone()[0]
        )


def test_repair_fixes_stale_shebang_and_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    with EventStore(home / "events.db"):
        pass
    script = project / "broken-script"
    script.write_text("#!/nonexistent/python -s\nprint('broken')\n", encoding="utf-8")
    script.chmod(0o755)

    first_actions = run_repair(cwd=project, mobius_home=home)
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    count_after_first = _repair_event_count(home, "shebang")
    second_actions = run_repair(cwd=project, mobius_home=home)
    count_after_second = _repair_event_count(home, "shebang")

    assert any(action.repair_type == "shebang" for action in first_actions)
    assert first_line == f"#!{sys.executable} -s"
    assert count_after_first == 1
    assert second_actions == []
    assert count_after_second == count_after_first


def test_repair_fixes_permissions_and_missing_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    with EventStore(home / "events.db"):
        pass
    home.chmod(0o755)
    (home / "events.db").chmod(0o644)

    actions = run_repair(cwd=tmp_path, mobius_home=home)
    config_payload = json.loads((home / "config.json").read_text(encoding="utf-8"))

    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "events.db").stat().st_mode & 0o777 == 0o600
    assert (home / "config.json").stat().st_mode & 0o777 == 0o600
    assert config_payload["profile"] == "dev"
    assert config_payload["log_level"] == "info"
    assert {action.repair_type for action in actions} >= {"permissions", "config"}


def test_repair_creates_missing_mobius_home_with_defaults(tmp_path: Path) -> None:
    home = tmp_path / "missing-home"

    actions = run_repair(cwd=tmp_path, mobius_home=home)

    assert home.is_dir()
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "events.db").stat().st_mode & 0o777 == 0o600
    assert (home / "config.json").exists()
    assert {action.repair_type for action in actions} >= {
        "mobius_home",
        "event_store",
        "config",
    }


def test_repair_rejects_file_mobius_home(tmp_path: Path) -> None:
    home = tmp_path / "home-file"
    home.write_text("not a directory", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        run_repair(cwd=tmp_path, mobius_home=home)


def test_repair_helpers_noop_for_clean_event_store_and_existing_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    paths = get_paths(home)
    with EventStore(paths.event_store):
        pass
    paths.config_file.write_text("{}", encoding="utf-8")
    paths.config_file.chmod(0o600)

    assert repair_module._repair_event_store(paths.event_store) == []
    assert repair_module._repair_config(paths.config_file) == []


def test_shebang_repair_handles_edge_cases(tmp_path: Path) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_text("not a script\n", encoding="utf-8")
    relative = tmp_path / "relative"
    relative.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    valid = tmp_path / "valid"
    valid.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    no_newline = tmp_path / "no-newline"
    no_newline.write_text("#!/nonexistent/no-newline", encoding="utf-8")

    assert repair_module._repair_shebang(plain, tmp_path) is None
    assert repair_module._repair_shebang(relative, tmp_path) is None
    assert repair_module._repair_shebang(valid, tmp_path) is None
    repaired = repair_module._repair_shebang(no_newline, tmp_path)

    assert repaired is not None
    assert repaired.target == "no-newline"
    assert no_newline.read_text(encoding="utf-8") == f"#!{sys.executable}\n"


def test_shebang_repair_handles_io_errors(tmp_path: Path) -> None:
    script = tmp_path / "script"
    script.write_text("#!/nonexistent/python\n", encoding="utf-8")

    with mock.patch.object(Path, "read_bytes", side_effect=OSError("read boom")):
        assert repair_module._repair_shebang(script, tmp_path) is None
    with mock.patch.object(Path, "write_bytes", side_effect=OSError("write boom")):
        assert repair_module._repair_shebang(script, tmp_path) is None


def test_emit_repair_events_handles_empty_and_store_errors(tmp_path: Path) -> None:
    repair_module._emit_repair_events(tmp_path / "events.db", [])
    action = RepairAction("config", "config.json", "missing", "created")

    with mock.patch.object(repair_module, "EventStore", side_effect=RuntimeError("boom")):
        repair_module._emit_repair_events(tmp_path / "events.db", [action])
