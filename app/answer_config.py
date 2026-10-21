"""Read optional answer experiment settings; never call the provider here."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .config import ConfigurationError, DEFAULT_ENV_PATH


@dataclass(frozen=True)
class AnswerSettings:
    answer_url: str
    answer_model: str
    answer_api_key: str = field(repr=False)


def load_answer_settings(env_path: Path = DEFAULT_ENV_PATH) -> AnswerSettings:
    file_values = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    values = {}
    for name in ("ANSWER_URL", "ANSWER_MODEL", "ANSWER_API_KEY"):
        value = os.environ.get(name, file_values.get(name))
        if not value or not value.strip():
            raise ConfigurationError(f"{name} is required.")
        value = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ConfigurationError(f"{name} must not contain control characters.")
        values[name] = value

    url = values["ANSWER_URL"]
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in url)
            and "\\" not in url
        )
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(
            "ANSWER_URL must be an HTTP/HTTPS endpoint without credentials, query or fragment."
        )

    return AnswerSettings(
        answer_url=url,
        answer_model=values["ANSWER_MODEL"],
        answer_api_key=values["ANSWER_API_KEY"],
    )
