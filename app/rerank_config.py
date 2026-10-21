"""Read optional rerank experiment settings; never call the provider here."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .config import ConfigurationError, DEFAULT_ENV_PATH


@dataclass(frozen=True)
class RerankSettings:
    rerank_url: str
    rerank_model: str
    rerank_api_key: str = field(repr=False)


def load_rerank_settings(env_path: Path = DEFAULT_ENV_PATH) -> RerankSettings:
    file_values = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    values = {}
    for name in ("RERANK_URL", "RERANK_MODEL", "RERANK_API_KEY"):
        value = os.environ.get(name, file_values.get(name))
        if not value or not value.strip():
            raise ConfigurationError(f"{name} is required.")
        value = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ConfigurationError(f"{name} must not contain control characters.")
        values[name] = value

    url = values["RERANK_URL"]
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
            "RERANK_URL must be an HTTP/HTTPS endpoint without credentials, query or fragment."
        )

    return RerankSettings(
        rerank_url=url,
        rerank_model=values["RERANK_MODEL"],
        rerank_api_key=values["RERANK_API_KEY"],
    )
