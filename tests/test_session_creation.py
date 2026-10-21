"""Session persistence uses temporary SQLite and test accounts only."""
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, text

from app.session_tokens import hash_session_token
from app.users import create_user


@pytest.fixture
def sessions(session_engine):
    assert (Path(__file__).parents[1]/'app/sessions.py').exists(), 'Create app/sessions.py first'
    module = import_module('app.sessions')
    user_id = create_user(session_engine, username='alice', password='Al1ce!23')
    return module, user_id


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(text('SELECT * FROM app_sessions')).mappings().all()


def test_session_saves_only_token_hash_with_correct_user_and_expiry(session_engine, sessions):
    module, user_id = sessions
    token, expires = module.create_session(session_engine, user_id=user_id)
    row, = rows(session_engine)
    assert str(UUID(row['session_id'])) == row['session_id']
    assert row['user_id'] == user_id
    assert row['token_hash'] == hash_session_token(token)
    assert token not in str(dict(row))
    assert row['revoked_at'] is None
    created = datetime.fromisoformat(row['created_at']).replace(tzinfo=timezone.utc)
    stored_expiry = datetime.fromisoformat(row['expires_at']).replace(tzinfo=timezone.utc)
    assert expires == stored_expiry
    assert expires.utcoffset().total_seconds() == 0
    assert (expires-created).total_seconds() == 7200


def test_two_logins_have_independent_sessions(session_engine, sessions):
    module, user_id = sessions
    first, _ = module.create_session(session_engine, user_id=user_id)
    second, _ = module.create_session(session_engine, user_id=user_id)
    saved = rows(session_engine)
    assert first != second and len(saved) == 2
    assert saved[0]['session_id'] != saved[1]['session_id']


@pytest.mark.parametrize('ttl', [0, -1, True, 1.5, 86401])
def test_invalid_lifetime_does_not_create_session(session_engine, sessions, ttl):
    module, user_id = sessions
    with pytest.raises(ValueError):
        module.create_session(session_engine, user_id=user_id, ttl_seconds=ttl)
    assert rows(session_engine) == []


def test_unknown_user_cannot_receive_session(session_engine, sessions):
    module, _ = sessions
    with pytest.raises(module.SessionUserUnavailable):
        module.create_session(session_engine, user_id='00000000-0000-4000-8000-000000000999')
    assert rows(session_engine) == []


def test_disabled_user_cannot_receive_session(session_engine, sessions):
    module, user_id = sessions
    with session_engine.begin() as conn:
        conn.execute(text('UPDATE app_users SET is_active=0 WHERE user_id=:id'), {'id':user_id})
    with pytest.raises(module.SessionUserUnavailable):
        module.create_session(session_engine, user_id=user_id)
    assert rows(session_engine) == []


def test_failure_before_commit_rolls_back_session(session_engine, sessions):
    module, user_id = sessions
    def fail(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('INSERT'):
            raise RuntimeError('test session insert failure')
    event.listen(session_engine, 'after_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            module.create_session(session_engine, user_id=user_id)
    finally:
        event.remove(session_engine, 'after_cursor_execute', fail)
    assert rows(session_engine) == []
