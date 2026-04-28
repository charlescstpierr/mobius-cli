"""Environment repair helpers for the Mobius CLI."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mobius.config import MobiusConfig, get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.doctor import _is_project_venv_script, _iter_candidate_files
from mobius.workflow.ids import readable_session_id

_EXPECTED_HOME_MODE = 0o700
_EXPECTED_DB_MODE = 0o600
_CONFIG_FILE_MODE = 0o600


@dataclass(frozen=True)
class RepairAction:
    """A repair applied by ``mobius repair``."""

    repair_type: str
    target: str
    before: str
    after: str

    def to_payload(self) -> dict[str, str]:
        """Return the JSON/event payload form of this repair."""
        return {
            "repair_type": self.repair_type,
            "target": self.target,
            "before": self.before,
            "after": self.after,
        }


def run_repair(*, cwd: Path, mobius_home: Path) -> list[RepairAction]:
    """Repair known Mobius environment problems and emit events for changes."""
    paths = get_paths(mobius_home)
    actions: list[RepairAction] = []

    actions.extend(_repair_mobius_home(paths.home))
    actions.extend(_repair_event_store(paths.event_store))
    actions.extend(_repair_config(paths.config_file))
    actions.extend(_repair_shebangs(cwd))

    _emit_repair_events(paths.event_store, actions)
    return actions


def _repair_mobius_home(home: Path) -> list[RepairAction]:
    if not home.exists():
        home.mkdir(parents=True, mode=_EXPECTED_HOME_MODE)
        os.chmod(home, _EXPECTED_HOME_MODE)
        return [
            RepairAction(
                "mobius_home",
                str(home),
                "missing",
                "directory mode 0700",
            )
        ]
    if not home.is_dir():
        msg = f"MOBIUS_HOME is not a directory: {home}"
        raise NotADirectoryError(msg)

    before = _mode(home)
    if before == _EXPECTED_HOME_MODE:
        return []
    os.chmod(home, _EXPECTED_HOME_MODE)
    return [
        RepairAction(
            "permissions",
            str(home),
            _format_mode(before),
            "0700",
        )
    ]


def _repair_event_store(event_store: Path) -> list[RepairAction]:
    existed = event_store.exists()
    before = _format_mode(_mode(event_store)) if existed else "missing"
    with EventStore(event_store):
        pass
    after_mode = _mode(event_store)
    if existed and after_mode == _EXPECTED_DB_MODE and before == "0600":
        return []
    if not existed:
        return [
            RepairAction(
                "event_store",
                str(event_store),
                "missing",
                "file mode 0600",
            )
        ]
    if before != "0600":
        return [
            RepairAction(
                "permissions",
                str(event_store),
                before,
                "0600",
            )
        ]
    return []


def _repair_config(config_file: Path) -> list[RepairAction]:
    if config_file.exists():
        return []
    config_file.parent.mkdir(parents=True, exist_ok=True, mode=_EXPECTED_HOME_MODE)
    os.chmod(config_file.parent, _EXPECTED_HOME_MODE)
    _write_default_config(config_file)
    return [
        RepairAction(
            "config",
            str(config_file),
            "missing",
            "default config mode 0600",
        )
    ]


def _write_default_config(config_file: Path) -> None:
    payload = json.dumps(MobiusConfig().to_mapping(), sort_keys=True, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=config_file.parent,
        prefix=f".{config_file.name}.",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(f"{payload}\n")
    os.chmod(temp_path, _CONFIG_FILE_MODE)
    temp_path.replace(config_file)
    os.chmod(config_file, _CONFIG_FILE_MODE)


def _repair_shebangs(root: Path) -> list[RepairAction]:
    actions: list[RepairAction] = []
    for path in _iter_candidate_files(root):
        action = _repair_shebang(path, root)
        if action is not None:
            actions.append(action)
    return actions


def _repair_shebang(path: Path, root: Path) -> RepairAction | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    if not content.startswith(b"#!"):
        return None

    line_end = content.find(b"\n")
    if line_end == -1:
        first_line = content
        remainder = b""
        newline = b"\n"
    else:
        first_line = content[:line_end]
        remainder = content[line_end + 1 :]
        newline = b"\n"

    shebang = first_line[2:].decode("utf-8", errors="replace").strip()
    parts = shebang.split(maxsplit=1)
    if not parts:
        return None
    target = parts[0]
    if not target.startswith("/"):
        return None

    target_path = Path(target)
    current_python = Path(sys.executable)
    stale_project_venv = (
        _is_project_venv_script(path)
        and target_path.resolve() != current_python.resolve()
    )
    missing_target = not target_path.exists()
    if not stale_project_venv and not missing_target:
        return None

    suffix = f" {parts[1]}" if len(parts) > 1 else ""
    replacement = f"#!{sys.executable}{suffix}".encode()
    try:
        path.write_bytes(replacement + newline + remainder)
    except OSError:
        return None

    try:
        display_path = str(path.relative_to(root))
    except ValueError:
        display_path = str(path)
    return RepairAction(
        "shebang",
        display_path,
        f"#!{shebang}",
        replacement.decode("utf-8"),
    )


def _emit_repair_events(event_store: Path, actions: list[RepairAction]) -> None:
    if not actions:
        return
    aggregate_id = readable_session_id("doctor", "environment repairs")
    try:
        with EventStore(event_store) as store:
            for action in actions:
                store.append_event(
                    aggregate_id,
                    "doctor.repair_applied",
                    action.to_payload(),
                )
    except Exception:
        return


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _format_mode(mode: int) -> str:
    return f"{mode:04o}"
