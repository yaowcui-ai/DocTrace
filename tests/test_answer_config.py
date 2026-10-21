import pytest

from app import answer_config
from app.config import ConfigurationError, load_settings


@pytest.fixture(autouse=True)
def clear_answer_environment(monkeypatch):
    for name in ("ANSWER_URL", "ANSWER_MODEL", "ANSWER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path, **overrides):
    values = {"ANSWER_URL": "https://api.deepseek.com/chat/completions",
              "ANSWER_MODEL": "deepseek-flash",
              "ANSWER_API_KEY": "test-secret-${UNSET}"}
    values.update(overrides)
    path = tmp_path / ".env"
    path.write_text("\n".join(f'{key}="{value}"' for key, value in values.items()), encoding="utf-8")
    return path


def test_loads_full_endpoint_and_hides_key_without_interpolation(tmp_path):
    settings = answer_config.load_answer_settings(write_config(tmp_path))
    assert settings.answer_url == "https://api.deepseek.com/chat/completions"
    assert settings.answer_model == "deepseek-flash"
    assert settings.answer_api_key == "test-secret-${UNSET}"
    assert "test-secret" not in repr(settings)


def test_environment_overrides_file(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setenv("ANSWER_MODEL", "test-model")
    assert answer_config.load_answer_settings(path).answer_model == "test-model"


@pytest.mark.parametrize("field", ["ANSWER_URL", "ANSWER_MODEL", "ANSWER_API_KEY"])
def test_missing_field_names_only_the_field(tmp_path, field):
    path = write_config(tmp_path, **{field: "   "})
    with pytest.raises(ConfigurationError) as error:
        answer_config.load_answer_settings(path)
    assert field in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("url", [
    "ftp://example.com", "https://", "https://example.com:bad",
    "https://example.com:99999", "https://user:test-secret@example.com",
    "https://example.com?key=test-secret", "https://example.com#fragment",
    "https://bad host/answer", "https://example.com\\answer",
])
def test_invalid_endpoint_is_rejected_without_echo(tmp_path, url):
    with pytest.raises(ConfigurationError) as error:
        answer_config.load_answer_settings(write_config(tmp_path, ANSWER_URL=url))
    assert "ANSWER_URL" in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("field", ["ANSWER_MODEL", "ANSWER_API_KEY"])
def test_control_characters_rejected(tmp_path, monkeypatch, field):
    path = write_config(tmp_path)
    monkeypatch.setenv(field, "test-secret\nextra")
    with pytest.raises(ConfigurationError):
        answer_config.load_answer_settings(path)


def test_existing_lightrag_configuration_does_not_require_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://127.0.0.1:9622")
    monkeypatch.setenv("LIGHTRAG_API_KEY", "service-test-key")
    assert load_settings(tmp_path / "absent.env").lightrag_url == "http://127.0.0.1:9622"
