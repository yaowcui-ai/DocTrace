from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import Engine, text

from .session_tokens import generate_session_token, hash_session_token


class SessionUserUnavailable(RuntimeError):
    pass


def create_session(
    engine: Engine,
    *,
    user_id: str,
    ttl_seconds: int = 7200,
) -> tuple[str, datetime]:
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
        raise ValueError("会话有效期必须为1～86400秒的整数。")

    token = generate_session_token()
    token_hash = hash_session_token(token)
    session_id = str(uuid4())

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)

    statement = text("""
        INSERT INTO app_sessions (
            session_id,
            token_hash,
            user_id,
            created_at,
            expires_at,
            revoked_at
        )
        SELECT
            :session_id,
            :token_hash,
            user_id,
            :created_at,
            :expires_at,
            NULL
        FROM app_users
        WHERE user_id = :user_id
          AND is_active = 1
    """)

    with engine.begin() as conn:
        result = conn.execute(
            statement,
            {
                "session_id": session_id,
                "token_hash": token_hash,
                "user_id": user_id,
                "created_at": now.replace(tzinfo=None),
                "expires_at": expires_at.replace(tzinfo=None),
            },
        )

        if result.rowcount != 1:
            raise SessionUserUnavailable("用户不存在或已停用。")

    return token, expires_at
def get_session_user(
    engine: Engine,
    token: str,
) -> dict | None:
    try:
        token_hash = hash_session_token(token)
    except ValueError:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        SELECT
            u.user_id,
            u.username
        FROM app_sessions AS s
        JOIN app_users AS u ON u.user_id = s.user_id
        WHERE s.token_hash = :token_hash
          AND s.expires_at > :now
          AND s.revoked_at IS NULL
          AND u.is_active = 1
    """)

    with engine.connect() as conn:
        row = conn.execute(
            statement,
            {
                "token_hash": token_hash,
                "now": now,
            },
        ).mappings().first()

    return dict(row) if row is not None else None
def revoke_session(
    engine: Engine,
    token: str,
) -> bool:
    try:
        token_hash = hash_session_token(token)
    except ValueError:
        return False

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        UPDATE app_sessions
        SET revoked_at = :now
        WHERE token_hash = :token_hash
          AND revoked_at IS NULL
    """)

    with engine.begin() as conn:
        result = conn.execute(
            statement,
            {
                "token_hash": token_hash,
                "now": now,
            },
        )

    return result.rowcount == 1