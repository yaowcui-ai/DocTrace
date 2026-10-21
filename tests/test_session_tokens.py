"""Session credential helpers; generated test tokens are never stored or sent."""
from importlib import import_module
from pathlib import Path
import re

import pytest


@pytest.fixture
def tokens():
    assert (Path(__file__).parents[1]/'app/session_tokens.py').exists(), 'Create app/session_tokens.py first'
    return import_module('app.session_tokens')


def test_generated_token_is_cookie_safe_and_has_expected_size(tokens):
    token = tokens.generate_session_token()
    assert isinstance(token, str)
    assert re.fullmatch(r'[A-Za-z0-9_-]{43}', token)


def test_separate_generations_do_not_reuse_a_token(tokens):
    assert tokens.generate_session_token() != tokens.generate_session_token()


def test_generator_requests_32_bytes_from_secrets(tokens, monkeypatch):
    calls = []
    def generate(size):
        calls.append(size)
        return 'A'*43
    monkeypatch.setattr(tokens.secrets, 'token_urlsafe', generate)
    assert tokens.generate_session_token() == 'A'*43
    assert calls == [32]


def test_same_token_has_a_stable_64_character_database_hash(tokens):
    token = tokens.generate_session_token()
    first = tokens.hash_session_token(token)
    assert re.fullmatch(r'[0-9a-f]{64}', first)
    assert first == tokens.hash_session_token(token)
    assert first != token


def test_hashing_does_not_lowercase_the_credential(tokens):
    assert tokens.hash_session_token('A'*43) != tokens.hash_session_token('a'*43)


@pytest.mark.parametrize('token', ['x'*42, 'x'*44, ' '*43, '中'*43, None])
def test_invalid_token_is_rejected_without_echoing_it(tokens, token):
    with pytest.raises(ValueError) as caught:
        tokens.hash_session_token(token)
    if token is not None:
        assert token not in str(caught.value)
