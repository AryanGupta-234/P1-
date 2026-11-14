import pytest

from senti.config import SentiSettings


def test_default_think_mode_is_auto_and_valid():
    settings = SentiSettings()
    assert settings.think_mode == "auto"
    assert settings.think is False  # only forced-on mode reports think=True
    settings.validate()


def test_think_mode_is_environment_configurable(monkeypatch):
    monkeypatch.setenv("SENTI_THINK", "off")
    assert SentiSettings.from_env().think_mode == "off"
    monkeypatch.setenv("SENTI_THINK", "ON")
    settings = SentiSettings.from_env()
    assert settings.think_mode == "on" and settings.think is True
    settings.validate()


def test_settings_reject_unknown_think_mode_and_unbounded_values():
    with pytest.raises(ValueError, match="think_mode"):
        SentiSettings(think_mode="sometimes").validate()
    with pytest.raises(ValueError, match="max_tool_rounds"):
        SentiSettings(max_tool_rounds=50).validate()
    with pytest.raises(ValueError, match="context_tokens"):
        SentiSettings(context_tokens=100).validate()
