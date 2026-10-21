import hashlib
import re
import secrets


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    if (
        not isinstance(token, str)
        or _TOKEN_PATTERN.fullmatch(token) is None
    ):
        raise ValueError("会话凭证格式无效。")

    return hashlib.sha256(token.encode("ascii")).hexdigest()