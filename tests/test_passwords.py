"""Password helpers use real Argon2, with test-only inputs and no DB/network."""
from importlib import import_module
from pathlib import Path

import pytest

TEST_PASSWORD = 'DocTrace-test-only!8274'


@pytest.fixture
def passwords():
    assert (Path(__file__).parents[1] / 'app/passwords.py').exists(), 'Create app/passwords.py first'
    return import_module('app.passwords')


def test_hash_uses_argon2id_and_fits_database_column(passwords):
    hashed = passwords.hash_password(TEST_PASSWORD)
    assert hashed.startswith('$argon2id$')
    assert TEST_PASSWORD not in hashed
    assert len(hashed) <= 255


def test_correct_password_verifies(passwords):
    hashed = passwords.hash_password(TEST_PASSWORD)
    assert passwords.verify_password(TEST_PASSWORD, hashed) is True


def test_wrong_password_is_rejected(passwords):
    hashed = passwords.hash_password(TEST_PASSWORD)
    assert passwords.verify_password('incorrect-test-password', hashed) is False


def test_same_password_has_different_salts_and_both_verify(passwords):
    first = passwords.hash_password(TEST_PASSWORD)
    second = passwords.hash_password(TEST_PASSWORD)
    assert first != second
    assert passwords.verify_password(TEST_PASSWORD, first) is True
    assert passwords.verify_password(TEST_PASSWORD, second) is True


def test_password_spaces_are_significant(passwords):
    padded = '  '+TEST_PASSWORD+'  '
    hashed = passwords.hash_password(padded)
    assert passwords.verify_password(padded, hashed) is True
    assert passwords.verify_password(padded.strip(), hashed) is False


def test_unicode_password_is_supported(passwords):
    password = '仅用于离线测试的密码！8274'
    hashed = passwords.hash_password(password)
    assert passwords.verify_password(password, hashed) is True


@pytest.mark.parametrize('stored', ['not-a-hash', '$argon2id$broken'])
def test_invalid_stored_hash_does_not_authenticate(passwords, stored):
    assert passwords.verify_password(TEST_PASSWORD, stored) is False
