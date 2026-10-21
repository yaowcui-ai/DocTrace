"""Effective session identity; test accounts and temporary SQLite only."""
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.session_tokens import generate_session_token
from app.users import create_user


@pytest.fixture
def session(session_engine):
    module = import_module('app.sessions')
    assert callable(getattr(module, 'get_session_user', None)), 'Add get_session_user() to app/sessions.py'
    user_id = create_user(session_engine, username='alice', password='Al1ce!23')
    token, expires = module.create_session(session_engine, user_id=user_id)
    return module, user_id, token, expires


def freeze(monkeypatch, module, moment):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)
    monkeypatch.setattr(module, 'datetime', FrozenDatetime)


def test_valid_session_returns_only_its_user_and_does_not_mutate_session(session_engine, session):
    module, user_id, token, _ = session
    with session_engine.connect() as conn:
        before = dict(conn.execute(text('SELECT * FROM app_sessions')).mappings().one())
    assert module.get_session_user(session_engine, token) == {'user_id':user_id, 'username':'alice'}
    with session_engine.connect() as conn:
        assert dict(conn.execute(text('SELECT * FROM app_sessions')).mappings().one()) == before


def test_unknown_validly_formatted_token_is_rejected(session_engine, session):
    module, _, _, _ = session
    assert module.get_session_user(session_engine, generate_session_token()) is None


@pytest.mark.parametrize('token', [None, 'not-a-token', ' '*43])
def test_invalid_cookie_is_treated_as_not_logged_in(session_engine, session, token):
    module, _, _, _ = session
    assert module.get_session_user(session_engine, token) is None


def test_expired_session_is_rejected(session_engine, session, monkeypatch):
    module, _, token, expires = session
    freeze(monkeypatch, module, expires+timedelta(seconds=1))
    assert module.get_session_user(session_engine, token) is None


def test_expiry_boundary_is_exclusive(session_engine, session, monkeypatch):
    module, _, token, expires = session
    freeze(monkeypatch, module, expires)
    assert module.get_session_user(session_engine, token) is None


def test_revoked_session_is_rejected(session_engine, session):
    module, _, token, _ = session
    with session_engine.begin() as conn:
        conn.execute(text('UPDATE app_sessions SET revoked_at=:now'), {'now':datetime.now(timezone.utc).replace(tzinfo=None)})
    assert module.get_session_user(session_engine, token) is None


def test_disabling_user_invalidates_previously_issued_session(session_engine, session):
    module, user_id, token, _ = session
    with session_engine.begin() as conn:
        conn.execute(text('UPDATE app_users SET is_active=0 WHERE user_id=:id'), {'id':user_id})
    assert module.get_session_user(session_engine, token) is None


def test_different_users_tokens_resolve_to_their_own_identity(session_engine, session):
    module, alice, first, _ = session
    bob = create_user(session_engine, username='bob', password='B0b!2345')
    second, _ = module.create_session(session_engine, user_id=bob)
    assert module.get_session_user(session_engine, first)['user_id'] == alice
    assert module.get_session_user(session_engine, second)['user_id'] == bob


def test_database_failure_is_not_hidden_as_invalid_session(session_engine, session, monkeypatch):
    module, _, token, _ = session
    def fail():
        raise SQLAlchemyError('test connection unavailable')
    monkeypatch.setattr(session_engine, 'connect', fail)
    with pytest.raises(SQLAlchemyError):
        module.get_session_user(session_engine, token)


def test_invalid_token_stops_before_database_access(session_engine, session, monkeypatch):
    module, _, _, _ = session
    monkeypatch.setattr(session_engine, 'connect', lambda: pytest.fail('Do not query with an invalid token'))
    assert module.get_session_user(session_engine, 'not-a-token') is None
