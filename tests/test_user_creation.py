"""Account creation with test-only passwords and temporary SQLite."""
from datetime import datetime, timezone
from importlib import import_module
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from app.passwords import verify_password

PASSWORD = 'Test!8274'


@pytest.fixture
def users():
    module = import_module('app.users')
    assert callable(getattr(module, 'create_user', None)), 'Add create_user() to app/users.py'
    return module


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(text('SELECT * FROM app_users')).mappings().all()


def test_account_stores_hash_and_utc_timestamps_not_plain_password(user_engine, users):
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    user_id = users.create_user(user_engine, username='alice', password=PASSWORD)
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    row, = rows(user_engine)
    assert str(UUID(user_id)) == user_id == row['user_id']
    assert row['username'] == 'alice' and row['is_active'] == 1
    assert row['password_hash'] != PASSWORD
    assert verify_password(PASSWORD, row['password_hash']) is True
    assert before <= datetime.fromisoformat(row['created_at']) <= after
    assert row['created_at'] == row['updated_at']


def test_two_accounts_with_same_password_have_independent_salts(user_engine, users):
    for username in ['alice', 'bob']:
        users.create_user(user_engine, username=username, password=PASSWORD)
    first, second = rows(user_engine)
    assert first['user_id'] != second['user_id']
    assert first['password_hash'] != second['password_hash']


def test_duplicate_username_does_not_replace_existing_account(user_engine, users):
    users.create_user(user_engine, username='alice', password=PASSWORD)
    original = dict(rows(user_engine)[0])
    with pytest.raises(IntegrityError):
        users.create_user(user_engine, username='alice', password='Other!8274')
    saved, = rows(user_engine)
    assert dict(saved) == original


@pytest.mark.parametrize('username', ['Alice', 'ab', 'a'*33, "alice' OR 1=1 --"])
def test_invalid_username_is_rejected_before_hashing(user_engine, users, monkeypatch, username):
    def forbidden(*args):
        pytest.fail('Validate before expensive hashing')
    monkeypatch.setattr(users, 'hash_password', forbidden, raising=False)
    with pytest.raises(ValueError):
        users.create_user(user_engine, username=username, password=PASSWORD)
    assert rows(user_engine) == []


@pytest.mark.parametrize('password', ['x'*5, 'x'*11])
def test_invalid_password_length_does_not_echo_or_store_password(user_engine, users, password):
    with pytest.raises(ValueError) as caught:
        users.create_user(user_engine, username='alice', password=password)
    assert password not in str(caught.value)
    assert rows(user_engine) == []


def test_password_spaces_are_preserved_during_account_creation(user_engine, users):
    padded = '  Ab12!?  '
    users.create_user(user_engine, username='alice', password=padded)
    row, = rows(user_engine)
    assert verify_password(padded, row['password_hash']) is True
    assert verify_password(padded.strip(), row['password_hash']) is False


def test_failure_before_commit_rolls_back_account(user_engine, users):
    def fail(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('INSERT'):
            raise RuntimeError('test failure before commit')
    event.listen(user_engine, 'after_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            users.create_user(user_engine, username='alice', password=PASSWORD)
    finally:
        event.remove(user_engine, 'after_cursor_execute', fail)
    assert rows(user_engine) == []


def test_hashing_happens_before_opening_insert_transaction(user_engine, users, monkeypatch):
    calls = []
    def on_begin(conn):
        calls.append('begin')
    def hash_test_password(password):
        calls.append('hash')
        return 'test-only-ordering-placeholder'
    monkeypatch.setattr(users, 'hash_password', hash_test_password, raising=False)
    event.listen(user_engine, 'begin', on_begin)
    try:
        users.create_user(user_engine, username='alice', password=PASSWORD)
    finally:
        event.remove(user_engine, 'begin', on_begin)
    assert calls == ['hash', 'begin']


@pytest.mark.parametrize('password', ['a'*6, 'b'*10])
def test_requested_password_length_boundaries_are_accepted(user_engine, users, password):
    users.create_user(user_engine, username='alice', password=password)
    row, = rows(user_engine)
    assert verify_password(password, row['password_hash']) is True
