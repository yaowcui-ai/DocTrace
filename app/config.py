"""Read backend configuration without sending requests or revealing credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class ConfigurationError(ValueError):
    """A configuration error whose message does not contain secret values."""


@dataclass(frozen=True)
class Settings:
    lightrag_url: str
    lightrag_api_key: str = field(repr=False)


def load_settings(
    env_path: Path = DEFAULT_ENV_PATH, *, url_name: str = "LIGHTRAG_URL"
) -> Settings:
    # Do not mutate process environment or interpolate characters in API keys.
    file_values = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    values = {}
    for name in (url_name, "LIGHTRAG_API_KEY"):
        value = os.environ.get(name, file_values.get(name))
        if not value or not value.strip():
            raise ConfigurationError(f"{name} is required.")
        values[name] = value.strip()

    url = values[url_name]
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() or ord(character) < 32 for character in url)
            and "\\" not in url
        )
        # Accessing port validates malformed or out-of-range ports.
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(
            f"{url_name} must be an HTTP/HTTPS service URL without credentials, query or fragment."
        )

    key = values["LIGHTRAG_API_KEY"]
    if any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise ConfigurationError("LIGHTRAG_API_KEY must not contain control characters.")

    return Settings(lightrag_url=url.rstrip("/"), lightrag_api_key=key)
