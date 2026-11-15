import pytest
from pydantic import ValidationError

from app.config import AppEnv, Settings


def test_fixtures_are_rejected_in_production():
    with pytest.raises(ValidationError, match="WINDCAST_ALLOW_FIXTURES"):
        Settings(app_env=AppEnv.PRODUCTION, allow_fixtures=True)


def test_production_defaults_disable_fixtures():
    assert Settings(app_env=AppEnv.PRODUCTION).allow_fixtures is False


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("WINDCAST_APP_ENV", "production")
    monkeypatch.setenv("WINDCAST_ALLOW_FIXTURES", "true")
    with pytest.raises(ValidationError):
        Settings()


def test_app_refuses_to_start_with_fixtures_in_production(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("WINDCAST_APP_ENV", "production")
    monkeypatch.setenv("WINDCAST_ALLOW_FIXTURES", "true")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        create_app()
