"""Load session policy without reading or displaying user credentials."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .config import ConfigurationError, DEFAULT_ENV_PATH

SESSION_COOKIE_NAME = os.environ.get('DOCTRACE_SESSION_COOKIE', 'doctrace_session')
if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', SESSION_COOKIE_NAME) is None:
    raise ConfigurationError('DOCTRACE_SESSION_COOKIE must be a valid cookie name.')


@dataclass(frozen=True)
class AuthSettings:
    allowed_origin: str
    cookie_secure: bool
    session_ttl_seconds: int


def load_auth_settings(env_path: Path = DEFAULT_ENV_PATH) -> AuthSettings:
    file_values = dotenv_values(env_path, encoding="utf-8", interpolate=False)

    def value(name: str, default: str) -> str:
        result = os.environ.get(name, file_values.get(name, default))
        if not isinstance(result, str) or not result.strip():
            raise ConfigurationError(f"{name} must not be empty.")
        return result.strip()

    origin = value("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:8001")
    secure = value("AUTH_COOKIE_SECURE", "false")
    ttl = value("AUTH_SESSION_TTL_SECONDS", "7200")
    if secure not in {"true", "false"}:
        raise ConfigurationError("AUTH_COOKIE_SECURE must be true or false.")
    if re.fullmatch(r"[0-9]{1,5}", ttl) is None or not 1 <= int(ttl) <= 86400:
        raise ConfigurationError("AUTH_SESSION_TTL_SECONDS must be an integer from 1 to 86400.")

    try:
        parsed = urlsplit(origin)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and "?" not in origin
            and "#" not in origin
            and "\\" not in origin
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in origin)
        )
        parsed.port  # Validate malformed or out-of-range ports.
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError("AUTH_ALLOWED_ORIGIN must be an HTTP/HTTPS origin without a path or credentials.")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigurationError("HTTP authentication is supported only on the local loopback host.")
    cookie_secure = secure == "true"
    if cookie_secure != (parsed.scheme == "https"):
        raise ConfigurationError("AUTH_COOKIE_SECURE must match whether AUTH_ALLOWED_ORIGIN uses HTTPS.")
    return AuthSettings(origin, cookie_secure, int(ttl))
