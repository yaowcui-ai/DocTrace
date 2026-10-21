"""Select the HR corpus explicitly; reuse the existing service-key/URL validation."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .config import ConfigurationError, DEFAULT_ENV_PATH, Settings, load_settings


@dataclass(frozen=True)
class MediumSettings:
    rag_settings: Settings
    max_total_tokens: int
    corpus_id: str


def load_medium_settings(env_path: Path = DEFAULT_ENV_PATH) -> MediumSettings:
    rag = load_settings(env_path, url_name="HR_LIGHTRAG_URL")
    values = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    raw = os.environ.get("HR_MAX_TOTAL_TOKENS", values.get("HR_MAX_TOTAL_TOKENS"))
    try:
        budget = int(raw)
        if budget <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ConfigurationError("HR_MAX_TOTAL_TOKENS must be a positive integer.") from None
    corpus_id = os.environ.get('HR_CORPUS_ID', values.get('HR_CORPUS_ID'))
    if not isinstance(corpus_id, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', corpus_id) is None:
        raise ConfigurationError('HR_CORPUS_ID must contain 1 to 64 letters, digits, underscores or hyphens.')
    return MediumSettings(rag_settings=rag, max_total_tokens=budget, corpus_id=corpus_id)
