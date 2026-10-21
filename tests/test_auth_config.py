import pytest

from app.config import ConfigurationError


@pytest.fixture
def config_env(tmp_path, monkeypatch):
    for name in ("AUTH_ALLOWED_ORIGIN", "AUTH_COOKIE_SECURE", "AUTH_SESSION_TTL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / ".env"


def test_local_defaults(config_env):
    from app.auth_config import load_auth_settings

    settings = load_auth_settings(config_env)
    assert settings.allowed_origin == "http://127.0.0.1:8001"
    assert settings.cookie_secure is False
    assert settings.session_ttl_seconds == 7200


def test_environment_overrides_file(config_env, monkeypatch):
    from app.auth_config import load_auth_settings

    config_env.write_text("AUTH_SESSION_TTL_SECONDS=60", encoding="utf-8")
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "120")
    assert load_auth_settings(config_env).session_ttl_seconds == 120


def test_https_requires_secure_cookie(config_env):
    from app.auth_config import load_auth_settings

    config_env.write_text(
        "AUTH_ALLOWED_ORIGIN=https://doctrace.example\nAUTH_COOKIE_SECURE=true",
        encoding="utf-8",
    )
    settings = load_auth_settings(config_env)
    assert settings.cookie_secure is True


@pytest.mark.parametrize("entry", [
    "AUTH_ALLOWED_ORIGIN=http://remote.example",
    "AUTH_ALLOWED_ORIGIN=http://user:password@127.0.0.1:8001",
    "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:8001/path",
    "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:8001/",
    "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:99999",
    "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:8001?x=1",
    "AUTH_ALLOWED_ORIGIN=https://doctrace.example",
    "AUTH_COOKIE_SECURE=true",
    "AUTH_COOKIE_SECURE=yes",
    "AUTH_SESSION_TTL_SECONDS=0",
    "AUTH_SESSION_TTL_SECONDS=86401",
    "AUTH_SESSION_TTL_SECONDS=1.5",
])
def test_invalid_settings(config_env, entry):
    from app.auth_config import load_auth_settings

    config_env.write_text(entry, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_auth_settings(config_env)
