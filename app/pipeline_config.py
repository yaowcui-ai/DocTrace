"""Load the context policy selected during development, without contacting providers."""

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .config import ConfigurationError, DEFAULT_ENV_PATH


@dataclass(frozen=True)
class PipelineSettings:
    max_chars: int
    min_score: float


def load_pipeline_settings(env_path: Path = DEFAULT_ENV_PATH) -> PipelineSettings:
    file_values = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    values = {}
    for name in ("CONTEXT_MAX_CHARS", "CONTEXT_MIN_SCORE"):
        value = os.environ.get(name, file_values.get(name))
        if value is None or not value.strip():
            raise ConfigurationError(f"{name} is required.")
        values[name] = value.strip()
    try:
        budget = int(values["CONTEXT_MAX_CHARS"])
        if budget <= 0:
            raise ValueError
    except ValueError:
        raise ConfigurationError("CONTEXT_MAX_CHARS must be a positive integer.") from None
    try:
        score = float(values["CONTEXT_MIN_SCORE"])
        if not math.isfinite(score):
            raise ValueError
    except ValueError:
        raise ConfigurationError("CONTEXT_MIN_SCORE must be finite.") from None
    return PipelineSettings(max_chars=budget, min_score=score)
