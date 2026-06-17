"""Behaviour tests for configuration load/save."""

import pytest

from claude_notify import config


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point config persistence at a throwaway file for the duration of a test."""
    path = tmp_path / "config.yaml"
    monkeypatch.setattr(config, "get_config_file", lambda: path)
    return path


def test_load_creates_and_persists_defaults_when_missing(config_file):
    loaded = config.load_config()

    assert loaded == config.get_default_config()
    assert config_file.exists()


def test_save_then_load_round_trips_a_value(config_file):
    data = config.get_default_config()
    data["timeout"] = 42

    config.save_config(data)

    assert config.load_config()["timeout"] == 42


def test_load_fills_missing_keys_from_defaults(config_file):
    config_file.write_text("timeout: 99\n")

    loaded = config.load_config()

    assert loaded["timeout"] == 99  # value from the file is preserved
    assert loaded["sound"] == config.get_default_config()["sound"]  # default filled in


def test_load_returns_defaults_on_corrupt_file(config_file):
    config_file.write_text("bad: [1, 2\n")  # invalid YAML

    assert config.load_config() == config.get_default_config()
