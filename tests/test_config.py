"""Tests for config.manager: deep merge, load, and atomic save."""

import json
import os
import sys
import tempfile

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.manager import _deep_merge, load_config, save_config, CONFIG_PATH


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"x": {"y": 1, "z": 2}}
        override = {"x": {"z": 99}}
        result = _deep_merge(base, override)
        assert result == {"x": {"y": 1, "z": 99}}

    def test_new_keys_in_base_preserved(self):
        base = {"a": 1, "new_key": "default"}
        override = {"a": 2}
        result = _deep_merge(base, override)
        assert result["new_key"] == "default"
        assert result["a"] == 2

    def test_override_replaces_non_dict_with_dict(self):
        base = {"a": "string"}
        override = {"a": {"nested": True}}
        result = _deep_merge(base, override)
        assert result["a"] == {"nested": True}

    def test_override_replaces_dict_with_non_dict(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        result = _deep_merge(base, override)
        assert result["a"] == "flat"

    def test_empty_override(self):
        base = {"a": 1}
        assert _deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert _deep_merge({}, override) == {"a": 1}

    def test_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        override = {"a": {"b": 2}}
        _deep_merge(base, override)
        assert base["a"]["b"] == 1


# ---------------------------------------------------------------------------
# save_config (atomic write)
# ---------------------------------------------------------------------------

class TestSaveConfig:
    def test_atomic_save_creates_valid_json(self, tmp_path, monkeypatch):
        config_path = str(tmp_path / "config.json")
        monkeypatch.setattr("config.manager.CONFIG_PATH", config_path)
        data = {"local_ae": {"ae_title": "TEST", "port": 1234}}
        save_config(data)
        with open(config_path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_no_temp_files_left_after_save(self, tmp_path, monkeypatch):
        config_path = str(tmp_path / "config.json")
        monkeypatch.setattr("config.manager.CONFIG_PATH", config_path)
        save_config({"key": "value"})
        files = os.listdir(tmp_path)
        assert files == ["config.json"]

    def test_save_overwrites_existing(self, tmp_path, monkeypatch):
        config_path = str(tmp_path / "config.json")
        monkeypatch.setattr("config.manager.CONFIG_PATH", config_path)
        save_config({"v": 1})
        save_config({"v": 2})
        with open(config_path) as f:
            assert json.load(f)["v"] == 2
