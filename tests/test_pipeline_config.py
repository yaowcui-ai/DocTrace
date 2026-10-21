import math

import pytest

from app import pipeline_config
from app.config import ConfigurationError


@pytest.fixture(autouse=True)
def clear_environment(monkeypatch):
    for name in ("CONTEXT_MAX_CHARS", "CONTEXT_MIN_SCORE"):
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path, budget="30000", score="0.3"):
    path = tmp_path / ".env"
    path.write_text(f"CONTEXT_MAX_CHARS={budget}\nCONTEXT_MIN_SCORE={score}\n", encoding="utf-8")
    return path


def test_loads_user_selected_policy(tmp_path):
    settings = pipeline_config.load_pipeline_settings(write_config(tmp_path))
    assert settings.max_chars == 30000
    assert settings.min_score == 0.3
    assert math.isfinite(settings.min_score)


def test_environment_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXT_MAX_CHARS", "20000")
    assert pipeline_config.load_pipeline_settings(write_config(tmp_path)).max_chars == 20000


@pytest.mark.parametrize("budget", ["0", "-1", "1.5", "true", ""])
def test_invalid_budget_is_rejected(tmp_path, budget):
    with pytest.raises(ConfigurationError):
        pipeline_config.load_pipeline_settings(write_config(tmp_path, budget=budget))


@pytest.mark.parametrize("score", ["nan", "inf", "bad", ""])
def test_invalid_threshold_is_rejected(tmp_path, score):
    with pytest.raises(ConfigurationError):
        pipeline_config.load_pipeline_settings(write_config(tmp_path, score=score))
