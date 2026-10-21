from sqlalchemy import Engine

from .passwords import hash_password, verify_password
from .users import get_user_by_username


# 仅用于占位计算，不对应真实账户。
_DUMMY_HASH = hash_password("dummy-only")


def authenticate_user(
    engine: Engine,
    username: str,
    password: str,
) -> dict | None:
    user = get_user_by_username(engine, username)

    stored_hash = (
        user["password_hash"]
        if user is not None
        else _DUMMY_HASH
    )
    password_matches = verify_password(password, stored_hash)

    if user is None or not password_matches or not user["is_active"]:
        return None

    return {
        "user_id": user["user_id"],
        "username": user["username"],
    }
    