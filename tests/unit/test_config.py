import json
from pathlib import Path

from mobius.config import MobiusConfig, get_paths, load_config, save_config


def test_get_paths_uses_mobius_home_for_state_and_event_store(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)

    assert paths.home == tmp_path
    assert paths.state_dir == tmp_path
    assert paths.event_store == tmp_path / "events.db"
    assert paths.config_file == tmp_path / "config.json"


def test_load_config_creates_state_dir_event_store_and_default_config(tmp_path: Path) -> None:
    loaded = load_config(tmp_path)

    assert loaded.paths.state_dir.stat().st_mode & 0o777 == 0o700
    assert loaded.paths.event_store.exists()
    assert loaded.paths.event_store.stat().st_mode & 0o777 == 0o600
    assert loaded.config.profile == "dev"
    assert loaded.config.log_level == "info"


def test_save_config_is_idempotent_for_same_value(tmp_path: Path) -> None:
    first = save_config(tmp_path, "log_level", "debug")
    second = save_config(tmp_path, "log_level", "debug")

    assert first == second
    assert load_config(tmp_path).config.log_level == "debug"
    assert json.loads((tmp_path / "config.json").read_text())["log_level"] == "debug"


def test_extra_config_keys_round_trip(tmp_path: Path) -> None:
    save_config(tmp_path, "custom_key", "custom-value")

    loaded = load_config(tmp_path)

    assert loaded.config.extra["custom_key"] == "custom-value"
    assert loaded.config.get_value("custom_key") == "custom-value"
    assert MobiusConfig.from_mapping(loaded.config.to_mapping()) == loaded.config
