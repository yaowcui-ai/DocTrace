"""Revoke one credential without changing unrelated login sessions."""
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from app.session_tokens import generate_session_token, hash_session_token
from app.users import create_user


@pytest.fixture
def session(session_engine):
    module = import_module('app.sessions')
    assert callable(getattr(module, 'revoke_session', None)), 'Add revoke_session() to app/sessions.py'
    user_id = create_user(session_engine, username='alice', password='Al1ce!23')
    token, _ = module.create_session(session_engine, user_id=user_id)
    return module, user_id, token


def row(engine, token):
    with engine.connect() as conn:
        return dict(conn.execute(text('SELECT * FROM app_sessions WHERE token_hash=:hash'),
            {'hash':hash_session_token(token)}).mappings().one())


def test_revoked_token_no_longer_resolves_to_user(session_engine, session):
    module, _, token = session
    assert module.revoke_session(session_engine, token) is True
    assert row(session_engine, token)['revoked_at'] is not None
    assert module.get_session_user(session_engine, token) is None


def test_repeated_revocation_does_not_overwrite_original_timestamp(session_engine, session):
    module, _, token = session
    assert module.revoke_session(session_engine, token) is True
    original = row(session_engine, token)
    assert module.revoke_session(session_engine, token) is False
    assert row(session_engine, token) == original


def test_other_session_for_same_user_stays_valid(session_engine, session):
    module, user_id, token = session
    other, _ = module.create_session(session_engine, user_id=user_id)
    assert module.revoke_session(session_engine, token) is True
    assert module.get_session_user(session_engine, other)['user_id'] == user_id


def test_unknown_token_does_not_change_existing_session(session_engine, session):
    module, _, token = session
    original = row(session_engine, token)
    assert module.revoke_session(session_engine, generate_session_token()) is False
    assert row(session_engine, token) == original


@pytest.mark.parametrize('token', [None, 'not-a-token', ' '*43])
def test_invalid_token_returns_false_without_database_access(session_engine, session, monkeypatch, token):
    module, _, _ = session
    monkeypatch.setattr(session_engine, 'connect', lambda: pytest.fail('Invalid token must not access DB'))
    assert module.revoke_session(session_engine, token) is False


def test_failure_before_commit_rolls_back_revocation(session_engine, session):
    module, _, token = session
    def fail(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('UPDATE'):
            raise RuntimeError('test revocation rollback')
    event.listen(session_engine, 'after_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            module.revoke_session(session_engine, token)
    finally:
        event.remove(session_engine, 'after_cursor_execute', fail)
    assert row(session_engine, token)['revoked_at'] is None


def test_database_failure_is_not_misreported_as_successful_logout(session_engine, session, monkeypatch):
    module, _, token = session
    def fail():
        raise SQLAlchemyError('test database unavailable')
    monkeypatch.setattr(session_engine, 'connect', fail)
    with pytest.raises(SQLAlchemyError):
        module.revoke_session(session_engine, token)


def test_expired_session_can_still_be_explicitly_revoked(session_engine, session):
    module, _, token = session
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_engine.begin() as conn:
        conn.execute(text('UPDATE app_sessions SET created_at=:created, expires_at=:expires'),
            {'created':now-timedelta(hours=2), 'expires':now-timedelta(hours=1)})
    assert module.revoke_session(session_engine, token) is True
