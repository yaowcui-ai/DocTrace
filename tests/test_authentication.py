"""Credential checking only; test passwords, temporary DB, no HTTP/model calls."""
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.users import create_user, get_user_by_username

PASSWORD = 'Al1ce!23'


@pytest.fixture
def auth(user_engine):
    assert (Path(__file__).parents[1]/'app/authentication.py').exists(), 'Create app/authentication.py first'
    module = import_module('app.authentication')
    create_user(user_engine, username='alice', password=PASSWORD)
    return module


def test_correct_credentials_return_only_public_identity(user_engine, auth):
    original = get_user_by_username(user_engine, 'alice')
    result = auth.authenticate_user(user_engine, 'alice', PASSWORD)
    assert result == {'user_id':original['user_id'], 'username':'alice'}
    assert 'password_hash' not in result


def test_wrong_password_is_rejected(user_engine, auth):
    assert auth.authenticate_user(user_engine, 'alice', 'Wrong!23') is None


def test_unknown_username_is_rejected(user_engine, auth):
    assert auth.authenticate_user(user_engine, 'unknown', PASSWORD) is None


def test_disabled_account_is_rejected_even_with_correct_password(user_engine, auth):
    with user_engine.begin() as conn:
        conn.execute(text("UPDATE app_users SET is_active=0 WHERE username='alice'"))
    assert auth.authenticate_user(user_engine, 'alice', PASSWORD) is None


def test_password_is_matched_against_the_requested_account(user_engine, auth):
    create_user(user_engine, username='bob', password='B0b!2345')
    assert auth.authenticate_user(user_engine, 'bob', PASSWORD) is None
    assert auth.authenticate_user(user_engine, 'bob', 'B0b!2345')['username'] == 'bob'


def test_password_whitespace_is_not_trimmed(user_engine, auth):
    password = '  Ab12!?  '
    create_user(user_engine, username='space_user', password=password)
    assert auth.authenticate_user(user_engine, 'space_user', password) is not None
    assert auth.authenticate_user(user_engine, 'space_user', password.strip()) is None


def test_unknown_account_still_runs_one_password_verification(user_engine, auth, monkeypatch):
    calls = []
    def verify(password, stored_hash):
        calls.append(stored_hash)
        return False
    monkeypatch.setattr(auth, 'verify_password', verify)
    assert auth.authenticate_user(user_engine, 'unknown', PASSWORD) is None
    assert len(calls) == 1 and calls[0].startswith('$argon2id$')


def test_matching_dummy_hash_cannot_authenticate_an_unknown_user(user_engine, auth, monkeypatch):
    monkeypatch.setattr(auth, 'verify_password', lambda *args: True)
    assert auth.authenticate_user(user_engine, 'unknown', PASSWORD) is None


def test_database_outage_is_not_disguised_as_incorrect_password(user_engine, auth, monkeypatch):
    def fail(*args):
        raise SQLAlchemyError('test database unavailable')
    monkeypatch.setattr(auth, 'get_user_by_username', fail)
    with pytest.raises(SQLAlchemyError):
        auth.authenticate_user(user_engine, 'alice', PASSWORD)


def test_corrupt_stored_hash_does_not_authenticate(user_engine, auth):
    with user_engine.begin() as conn:
        conn.execute(text("UPDATE app_users SET password_hash='invalid-test-hash' WHERE username='alice'"))
    assert auth.authenticate_user(user_engine, 'alice', PASSWORD) is None
