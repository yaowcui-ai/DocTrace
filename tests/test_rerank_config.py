import pytest

from app import rerank_config
from app.config import ConfigurationError, load_settings


@pytest.fixture(autouse=True)
def clear_rerank_environment(monkeypatch):
    for name in ("RERANK_URL", "RERANK_MODEL", "RERANK_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path, **overrides):
    values = {"RERANK_URL": "https://api.siliconflow.cn/v1/rerank",
              "RERANK_MODEL": "BAAI/bge-reranker-v2-m3",
              "RERANK_API_KEY": "test-secret-${UNSET}"}
    values.update(overrides)
    path = tmp_path / ".env"
    path.write_text("\n".join(f'{key}="{value}"' for key, value in values.items()), encoding="utf-8")
    return path


def test_loads_full_endpoint_and_hides_key_without_interpolation(tmp_path):
    settings = rerank_config.load_rerank_settings(write_config(tmp_path))
    assert settings.rerank_url == "https://api.siliconflow.cn/v1/rerank"
    assert settings.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert settings.rerank_api_key == "test-secret-${UNSET}"
    assert "test-secret" not in repr(settings)


def test_environment_overrides_file(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setenv("RERANK_MODEL", "test-model")
    assert rerank_config.load_rerank_settings(path).rerank_model == "test-model"


@pytest.mark.parametrize("field", ["RERANK_URL", "RERANK_MODEL", "RERANK_API_KEY"])
def test_missing_field_names_only_the_field(tmp_path, field):
    path = write_config(tmp_path, **{field: "   "})
    with pytest.raises(ConfigurationError) as error:
        rerank_config.load_rerank_settings(path)
    assert field in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("url", [
    "ftp://example.com", "https://", "https://example.com:bad",
    "https://example.com:99999", "https://user:test-secret@example.com",
    "https://example.com?key=test-secret", "https://example.com#fragment",
    "https://bad host/rerank", "https://example.com\\rerank",
])
def test_invalid_endpoint_is_rejected_without_echo(tmp_path, url):
    with pytest.raises(ConfigurationError) as error:
        rerank_config.load_rerank_settings(write_config(tmp_path, RERANK_URL=url))
    assert "RERANK_URL" in str(error.value)
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("field", ["RERANK_MODEL", "RERANK_API_KEY"])
def test_control_characters_rejected(tmp_path, monkeypatch, field):
    path = write_config(tmp_path)
    monkeypatch.setenv(field, "test-secret\nextra")
    with pytest.raises(ConfigurationError):
        rerank_config.load_rerank_settings(path)


def test_existing_lightrag_configuration_does_not_require_rerank(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTRAG_URL", "http://127.0.0.1:9622")
    monkeypatch.setenv("LIGHTRAG_API_KEY", "service-test-key")
    assert load_settings(tmp_path / "absent.env").lightrag_url == "http://127.0.0.1:9622"
