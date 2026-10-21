import pytest
from pathlib import Path
import app.config as config_module

from app.config import ConfigurationError, DEFAULT_ENV_PATH, load_settings


@pytest.fixture(autouse=True)
def clear_configuration_environment(monkeypatch):
    monkeypatch.delenv("LIGHTRAG_URL", raising=False)
    monkeypatch.delenv("LIGHTRAG_API_KEY", raising=False)


def test_default_env_is_in_application_directory():
    assert DEFAULT_ENV_PATH.parent == Path(config_module.__file__).resolve().parent.parent
    assert DEFAULT_ENV_PATH.name == ".env"


def test_loads_file_without_exposing_key(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        'LIGHTRAG_URL=http://127.0.0.1:9621/\nLIGHTRAG_API_KEY="test-secret-${UNSET}"\n',
        encoding="utf-8",
    )
    settings = load_settings(env_path)
    assert settings.lightrag_url == "http://127.0.0.1:9621"
    assert settings.lightrag_api_key == "test-secret-${UNSET}"
    assert settings.lightrag_api_key not in repr(settings)


def test_environment_overrides_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LIGHTRAG_URL=http://file.example\nLIGHTRAG_API_KEY=file-key\n")
    monkeypatch.setenv("LIGHTRAG_URL", "https://environment.example/rag/")
    monkeypatch.setenv("LIGHTRAG_API_KEY", "environment-key")
    settings = load_settings(env_path)
    assert settings.lightrag_url == "https://environment.example/rag"
    assert settings.lightrag_api_key == "environment-key"


@pytest.mark.parametrize("missing", ["LIGHTRAG_URL", "LIGHTRAG_API_KEY"])
def test_missing_configuration_names_field(tmp_path, monkeypatch, missing):
    monkeypatch.setenv("LIGHTRAG_URL", "http://localhost:9621")
    monkeypatch.setenv("LIGHTRAG_API_KEY", "test-secret")
    monkeypatch.setenv(missing, "   ")
    with pytest.raises(ConfigurationError) as error:
        load_settings(tmp_path / "absent.env")
    assert missing in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("url", [
    "localhost:9621", "ftp://example.com", "http://", "http://example.com:bad",
    "http://user:test-secret@example.com", "http://example.com?key=test-secret",
    "http://example.com#test-secret", "http://bad host", "http://example.com:99999",
])
def test_invalid_url_never_echoes_configuration(tmp_path, monkeypatch, url):
    monkeypatch.setenv("LIGHTRAG_URL", url)
    monkeypatch.setenv("LIGHTRAG_API_KEY", "test-secret")
    with pytest.raises(ConfigurationError) as error:
        load_settings(tmp_path / "absent.env")
    assert "LIGHTRAG_URL" in str(error.value)
    assert "test-secret" not in str(error.value)


def test_key_with_newline_is_rejected_without_leaking(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://localhost:9621")
    monkeypatch.setenv("LIGHTRAG_API_KEY", "test-secret\nextra")
    with pytest.raises(ConfigurationError) as error:
        load_settings(tmp_path / "absent.env")
    assert "LIGHTRAG_API_KEY" in str(error.value)
    assert "test-secret" not in str(error.value)
