from senti.config import SentiSettings

def test_think_is_forced_false_and_not_environment_overridable(monkeypatch):
    monkeypatch.setenv("SENTI_THINK", "true")
    settings = SentiSettings.from_env()
    assert settings.think is False
    settings.validate()

def test_settings_reject_think_true():
    settings = SentiSettings(think=True)
    try:
        settings.validate()
    except ValueError as exc:
        assert "think=False" in str(exc)
    else:
        raise AssertionError("think=True must be rejected")
