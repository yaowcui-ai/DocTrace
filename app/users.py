from sqlalchemy import Engine, text
import re
from datetime import datetime, timezone
from uuid import uuid4

from .passwords import hash_password

MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 10

def get_user_by_username(
    engine: Engine,
    username: str,
) -> dict | None:
    statement = text("""
        SELECT
            user_id,
            username,
            password_hash,
            is_active,
            created_at,
            updated_at
        FROM app_users
        WHERE username = :username
    """)

    with engine.connect() as conn:
        row = conn.execute(
            statement,
            {"username": username},
        ).mappings().first()

    return dict(row) if row is not None else None

def create_user(
    engine: Engine,
    *,
    username: str,
    password: str,
) -> str:
    if (
        not isinstance(username, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{2,31}", username) is None
    ):
        raise ValueError("用户名格式不符合要求。")

    if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(f"密码长度必须为{MIN_PASSWORD_LENGTH}～{MAX_PASSWORD_LENGTH}个字符。")

    stored_hash = hash_password(password)
    user_id = str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        INSERT INTO app_users (
            user_id,
            username,
            password_hash,
            is_active,
            created_at,
            updated_at
        )
        VALUES (
            :user_id,
            :username,
            :password_hash,
            1,
            :created_at,
            :updated_at
        )
    """)

    with engine.begin() as conn:
        conn.execute(
            statement,
            {
                "user_id": user_id,
                "username": username,
                "password_hash": stored_hash,
                "created_at": now,
                "updated_at": now,
            },
        )

    return user_id
