"""Account lookup security/identity checks with temporary SQLite only."""
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture
def users(user_engine):
    # Deliberately fake hashes: this suite tests lookup, not authentication.
    with user_engine.begin() as conn:
        for name, user_id in [('alice','00000000-0000-4000-8000-000000000001'), ('bob','00000000-0000-4000-8000-000000000002')]:
            conn.execute(text('''
                INSERT INTO app_users (user_id, username, password_hash, is_active, created_at, updated_at)
                VALUES (:id, :name, :hash, 1, '2026-10-17 00:00:00', '2026-10-17 00:00:00')
            '''), {'id':user_id, 'name':name, 'hash':'test-only-hash-'+name})
    assert (Path(__file__).parents[1]/'app/users.py').exists(), 'Create app/users.py first'
    return import_module('app.users')


def test_lookup_returns_requested_users_identity_and_hash(user_engine, users):
    row = users.get_user_by_username(user_engine, 'alice')
    assert isinstance(row, dict)
    assert row['user_id'] == '00000000-0000-4000-8000-000000000001'
    assert row['username'] == 'alice'
    assert row['password_hash'] == 'test-only-hash-alice'
    assert row['is_active'] == 1


def test_another_username_returns_its_own_hash(user_engine, users):
    row = users.get_user_by_username(user_engine, 'bob')
    assert row['password_hash'] == 'test-only-hash-bob'


@pytest.mark.parametrize('name', ['missing', "alice' OR 1=1 --", 'Alice'])
def test_missing_injected_or_differently_cased_name_does_not_match(user_engine, users, name):
    assert users.get_user_by_username(user_engine, name) is None


def test_lookup_returns_inactive_state_without_modifying_it(user_engine, users):
    with user_engine.begin() as conn:
        conn.execute(text("UPDATE app_users SET is_active=0 WHERE username='alice'"))
    row = users.get_user_by_username(user_engine, 'alice')
    assert row['is_active'] == 0
    with user_engine.connect() as conn:
        assert conn.execute(text("SELECT is_active FROM app_users WHERE username='alice'")).scalar_one() == 0


def test_database_failure_is_not_disguised_as_unknown_username(user_engine, users, monkeypatch):
    def fail():
        raise SQLAlchemyError('test connection unavailable')
    monkeypatch.setattr(user_engine, 'connect', fail)
    with pytest.raises(SQLAlchemyError):
        users.get_user_by_username(user_engine, 'alice')
