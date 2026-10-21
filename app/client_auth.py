"""Authenticate a CLI HTTP client without storing passwords or cookies on disk."""
import getpass
import warnings

import httpx2 as httpx
from pydantic import ValidationError

from .auth_config import SESSION_COOKIE_NAME, load_auth_settings
from .auth_schemas import CurrentUserResponse
from .config import ConfigurationError


def login_evaluation_client(client, base_url: str, username: str):
    settings = load_auth_settings()
    if base_url != settings.allowed_origin:
        raise ConfigurationError("Evaluation target must match AUTH_ALLOWED_ORIGIN before login.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('DocTrace password (hidden): ')
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        raise ConfigurationError("Secure password input unavailable or cancelled; no question submitted.") from None
    try:
        response=client.post(base_url+'/auth/login',headers={'Origin':settings.allowed_origin},json={'username':username,'password':password})
        if response.status_code != 200:
            raise ConfigurationError("DocTrace login failed; no question submitted.")
        user=CurrentUserResponse.model_validate(response.json())
        if not client.cookies.get(SESSION_COOKIE_NAME):
            raise ConfigurationError("DocTrace did not return a session cookie.")
    except (httpx.RequestError, ValidationError, ValueError) as error:
        if isinstance(error,ConfigurationError):
            raise
        raise ConfigurationError("Unable to confirm DocTrace login; no question submitted.") from None
    finally:
        password=None
    client.headers['Origin']=settings.allowed_origin
    client.headers['X-DocTrace-User-ID']=str(user.user_id)
