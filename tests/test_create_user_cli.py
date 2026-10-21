"""Local CLI input/output safety with test-only passwords and temporary DB."""
from importlib import import_module
from pathlib import Path
import warnings

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.passwords import verify_password
from app.users import get_user_by_username

PASSWORD = 'Test!8274'


@pytest.fixture
def cli(monkeypatch, user_engine):
    assert (Path(__file__).parents[1]/'app/create_user.py').exists(), 'Create app/create_user.py first'
    module = import_module('app.create_user')
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(module, 'getpass', lambda prompt: next(answers))
    monkeypatch.setattr(module, 'load_database_settings', lambda: object())
    monkeypatch.setattr(module, 'create_db_engine', lambda settings: user_engine)
    return module


def test_cli_creates_account_without_printing_password_or_hash(cli, user_engine, capsys):
    assert cli.main(['--username','alice']) == 0
    row = get_user_by_username(user_engine, 'alice')
    assert verify_password(PASSWORD, row['password_hash'])
    output = capsys.readouterr().out
    assert 'User created' in output and row['user_id'] in output
    assert PASSWORD not in output and row['password_hash'] not in output


def test_confirmation_mismatch_stops_before_database(cli, monkeypatch, capsys):
    answers = iter([PASSWORD, PASSWORD+'different'])
    monkeypatch.setattr(cli, 'getpass', lambda prompt: next(answers))
    monkeypatch.setattr(cli, 'create_db_engine', lambda settings: pytest.fail('Do not open DB on mismatch'))
    assert cli.main(['--username','alice']) == 1
    assert PASSWORD not in capsys.readouterr().out


def test_existing_username_is_not_overwritten(cli, user_engine, monkeypatch, capsys):
    assert cli.main(['--username','alice']) == 0
    original = get_user_by_username(user_engine, 'alice')
    monkeypatch.setattr(cli, 'getpass', lambda prompt: 'Other!8274')
    assert cli.main(['--username','alice']) == 1
    assert get_user_by_username(user_engine, 'alice') == original
    output = capsys.readouterr().out
    assert PASSWORD not in output and original['password_hash'] not in output


def test_unsafe_echo_fallback_is_refused(cli, monkeypatch):
    def unsafe(prompt):
        warnings.warn('test echo fallback', cli.GetPassWarning)
        return PASSWORD
    monkeypatch.setattr(cli, 'getpass', unsafe)
    monkeypatch.setattr(cli, 'create_db_engine', lambda settings: pytest.fail('Do not open DB after unsafe input'))
    assert cli.main(['--username','alice']) == 1


def test_database_error_does_not_echo_raw_error_or_password(cli, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-db-secret '+PASSWORD)
    monkeypatch.setattr(cli, 'create_user', fail)
    assert cli.main(['--username','alice']) == 1
    output = capsys.readouterr().out
    assert 'private-db-secret' not in output and PASSWORD not in output


def test_invalid_password_creates_no_account(cli, user_engine, monkeypatch):
    monkeypatch.setattr(cli, 'getpass', lambda prompt: 'short')
    assert cli.main(['--username','alice']) == 1
    assert get_user_by_username(user_engine, 'alice') is None


def test_eof_aborts_without_database_access(cli, monkeypatch):
    def eof(prompt):
        raise EOFError()
    monkeypatch.setattr(cli, 'getpass', eof)
    monkeypatch.setattr(cli, 'create_db_engine', lambda settings: pytest.fail('Do not open DB on EOF'))
    assert cli.main(['--username','alice']) == 1


def test_keyboard_interrupt_aborts_without_database_access(cli, monkeypatch):
    def interrupt(prompt):
        raise KeyboardInterrupt()
    monkeypatch.setattr(cli, 'getpass', interrupt)
    monkeypatch.setattr(cli, 'create_db_engine', lambda settings: pytest.fail('Do not open DB on cancellation'))
    assert cli.main(['--username','alice']) == 130


def test_configuration_error_is_reported_as_configuration_not_password(cli, monkeypatch, capsys):
    def fail():
        raise cli.ConfigurationError('private-setting')
    monkeypatch.setattr(cli, 'load_database_settings', fail)
    assert cli.main(['--username','alice']) == 1
    output = capsys.readouterr().out
    assert 'Database configuration' in output
    assert 'private-setting' not in output
