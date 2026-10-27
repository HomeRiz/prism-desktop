import json
import os
import sys

import pytest

from core import config_manager as cm
from core.config_manager import ConfigManager


@pytest.fixture
def token_store(monkeypatch):
    state = {"token": "", "stored": []}

    def fake_store(token):
        state["token"] = token
        state["stored"].append(token)

    monkeypatch.setattr(cm, "store_token", fake_store)
    monkeypatch.setattr(cm, "load_token", lambda: state["token"])
    return state


def write_config(config_dir, data, name="config.json"):
    path = config_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_defaults_when_no_file_exists(config_dir, token_store):
    manager = ConfigManager()
    assert manager.config["home_assistant"] == {"url": "", "token": ""}
    assert manager.config["appearance"]["language"] == "en"
    assert manager.config["appearance"]["pages"] == 1
    assert manager.config["buttons"] == []
    assert manager.config["welcome_shown"] is False


def test_default_tray_position_depends_on_platform(config_dir, token_store):
    expected = "top" if sys.platform == "darwin" else "bottom"
    assert ConfigManager().config["appearance"]["tray_position"] == expected


def test_defaults_are_fresh_copies_per_instance(config_dir, token_store):
    first = ConfigManager()
    first.config["buttons"].append({"x": 1})
    assert ConfigManager.load_config(first)["buttons"] == []


def test_constructor_writes_default_file_to_disk(config_dir, token_store):
    ConfigManager()
    on_disk = json.loads((config_dir / "config.json").read_text())
    assert on_disk["appearance"]["theme"] == "system"


def test_custom_filename_is_used(config_dir, token_store):
    manager = ConfigManager("other.json")
    assert manager.config_path == config_dir / "other.json"
    assert (config_dir / "other.json").exists()


def test_loads_existing_values(config_dir, token_store):
    write_config(config_dir, {"home_assistant": {"url": "http://ha:8123", "token": ""},
                              "appearance": {"theme": "dark"}})
    manager = ConfigManager()
    assert manager.config["home_assistant"]["url"] == "http://ha:8123"
    assert manager.config["appearance"]["theme"] == "dark"


def test_token_from_secure_storage_replaces_file_value(config_dir, token_store):
    token_store["token"] = "secure-token"
    write_config(config_dir, {"home_assistant": {"url": "u", "token": "stale"}})
    manager = ConfigManager()
    assert manager.config["home_assistant"]["token"] == "secure-token"
    assert "stale" not in token_store["stored"]


def test_plaintext_token_is_migrated_and_scrubbed_from_disk(config_dir, token_store):
    path = write_config(config_dir, {"home_assistant": {"url": "u", "token": "plain-secret"}})
    manager = ConfigManager()
    assert manager.config["home_assistant"]["token"] == "plain-secret"
    assert token_store["token"] == "plain-secret"
    assert "plain-secret" not in path.read_text()
    assert json.loads(path.read_text())["home_assistant"]["token"] == ""


def test_save_config_never_writes_token_to_disk(config_dir, token_store):
    manager = ConfigManager()
    manager.config["home_assistant"]["token"] = "new-token"
    manager.save_config()
    raw = (config_dir / "config.json").read_text()
    assert "new-token" not in raw
    assert token_store["token"] == "new-token"
    assert manager.config["home_assistant"]["token"] == "new-token"


def test_save_config_without_token_does_not_touch_storage(config_dir, token_store):
    ConfigManager()
    assert token_store["stored"] == []


def test_legacy_slot_is_migrated_to_row_and_col(config_dir, token_store):
    write_config(config_dir, {"appearance": {"cols": 3},
                              "buttons": [{"slot": 7, "entity_id": "light.a"}]})
    button = ConfigManager().config["buttons"][0]
    assert (button["row"], button["col"]) == (2, 1)


def test_legacy_slot_uses_default_four_columns(config_dir, token_store):
    write_config(config_dir, {"buttons": [{"slot": 5}]})
    button = ConfigManager().config["buttons"][0]
    assert (button["row"], button["col"]) == (1, 1)


def test_existing_row_is_not_overwritten_by_slot(config_dir, token_store):
    write_config(config_dir, {"buttons": [{"slot": 9, "row": 0, "col": 0}]})
    button = ConfigManager().config["buttons"][0]
    assert (button["row"], button["col"]) == (0, 0)


def test_buttons_without_page_get_page_zero(config_dir, token_store):
    write_config(config_dir, {"buttons": [{"row": 0, "col": 0}, {"row": 0, "col": 1, "page": 2}]})
    pages = [b["page"] for b in ConfigManager().config["buttons"]]
    assert pages == [0, 2]


def test_corrupt_json_is_backed_up_and_defaults_returned(config_dir, token_store):
    path = config_dir / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    manager = ConfigManager()
    backup = config_dir / "config.json.bak"
    assert backup.read_text() == "{not valid json"
    assert manager.config["buttons"] == []
    assert json.loads(path.read_text())["appearance"]["theme"] == "system"


def test_corrupt_backup_overwrites_previous_backup(config_dir, token_store):
    (config_dir / "config.json.bak").write_text("old backup")
    (config_dir / "config.json").write_text("garbage")
    ConfigManager()
    assert (config_dir / "config.json.bak").read_text() == "garbage"


def test_non_object_json_is_treated_as_corrupt(config_dir, token_store):
    (config_dir / "config.json").write_text("[1, 2, 3]")
    manager = ConfigManager()
    assert manager.config["home_assistant"] == {"url": "", "token": ""}
    assert (config_dir / "config.json.bak").exists()


def test_backup_failure_is_swallowed(config_dir, token_store, monkeypatch):
    (config_dir / "config.json").write_text("garbage")

    def boom(src, dst):
        raise OSError("read-only")

    monkeypatch.setattr(cm.os, "replace", boom)
    manager = ConfigManager()
    assert manager.config["buttons"] == []


def test_save_raw_config_writes_given_dict_without_touching_state(config_dir, token_store):
    manager = ConfigManager()
    manager.save_raw_config({"custom": True})
    assert json.loads((config_dir / "config.json").read_text()) == {"custom": True}
    assert "custom" not in manager.config


def test_save_raw_config_leaves_no_temp_files(config_dir, token_store):
    manager = ConfigManager()
    manager.save_raw_config({"a": 1})
    assert [p.name for p in config_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_save_raw_config_failure_keeps_original_and_cleans_temp(config_dir, token_store):
    manager = ConfigManager()
    original = (config_dir / "config.json").read_text()
    manager.save_raw_config({"bad": {1, 2}})
    assert (config_dir / "config.json").read_text() == original
    assert [p for p in config_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_save_config_swallows_storage_errors(config_dir, token_store, monkeypatch):
    manager = ConfigManager()
    manager.config["home_assistant"]["token"] = "t"

    def boom(token):
        raise RuntimeError("no storage")

    monkeypatch.setattr(cm, "store_token", boom)
    manager.save_config()


def test_save_config_roundtrip_through_new_instance(config_dir, token_store):
    manager = ConfigManager()
    manager.config["appearance"]["rows"] = 5
    manager.config["buttons"].append({"row": 1, "col": 1, "page": 0, "entity_id": "light.x"})
    manager.save_config()
    reloaded = ConfigManager()
    assert reloaded.config["appearance"]["rows"] == 5
    assert reloaded.config["buttons"][0]["entity_id"] == "light.x"


@pytest.mark.skipif(os.name != "posix", reason="chmod semantics are posix only")
def test_unreadable_config_falls_back_to_defaults(config_dir, token_store):
    path = write_config(config_dir, {"appearance": {"theme": "dark"}})
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("running with privileges that ignore file modes")
        manager = ConfigManager()
        assert manager.config["appearance"]["theme"] == "system"
    finally:
        for candidate in config_dir.iterdir():
            candidate.chmod(0o600)
