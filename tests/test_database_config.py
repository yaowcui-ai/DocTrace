"""Read connection settings without connecting, altering passwords or leaking secrets."""
import socket

import pytest

from app import database_config
from app.config import ConfigurationError

KEYS=('MYSQL_HOST','MYSQL_PORT','MYSQL_DATABASE','MYSQL_USER','MYSQL_PASSWORD')


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in KEYS:monkeypatch.delenv(key,raising=False)


def config(tmp_path,**changes):
    values=dict(zip(KEYS,['127.0.0.1','3306','doctrace','doctrace_app',"'local-test-secret'"]))
    values.update(changes)
    path=tmp_path/'.env'
    path.write_text('\n'.join(k+'='+v for k,v in values.items() if v is not None),encoding='utf-8')
    return path


def test_loads_local_app_settings_without_opening_a_connection(tmp_path,monkeypatch):
    def forbidden(*a,**kw):pytest.fail('Configuration loading must not connect')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    settings=database_config.load_database_settings(config(tmp_path))
    assert (settings.host,settings.port,settings.database,settings.user)==('127.0.0.1',3306,'doctrace','doctrace_app')
    assert settings.password=='local-test-secret'
    assert 'local-test-secret' not in repr(settings)


def test_preserves_special_characters_and_significant_password_spaces(tmp_path):
    settings=database_config.load_database_settings(config(tmp_path,MYSQL_PASSWORD="' A@#${NOT_AN_ENV}:/$ end '"))
    assert settings.password==' A@#${NOT_AN_ENV}:/$ end '


def test_environment_can_override_file_without_being_modified(tmp_path,monkeypatch):
    monkeypatch.setenv('MYSQL_PASSWORD','environment-secret')
    settings=database_config.load_database_settings(config(tmp_path))
    assert settings.password=='environment-secret'


@pytest.mark.parametrize('key',KEYS)
def test_missing_setting_is_rejected_without_echoing_other_secret(tmp_path,key):
    with pytest.raises(ConfigurationError) as error:
        database_config.load_database_settings(config(tmp_path,**{key:None}))
    assert 'local-test-secret' not in str(error.value)


@pytest.mark.parametrize('port',['0','65536','-1','1.5','true',''])
def test_invalid_port_is_rejected(tmp_path,port):
    with pytest.raises(ConfigurationError):database_config.load_database_settings(config(tmp_path,MYSQL_PORT=port))


def test_control_characters_in_environment_are_rejected_without_echo(monkeypatch,tmp_path):
    monkeypatch.setenv('MYSQL_PASSWORD','sensitive\nvalue')
    with pytest.raises(ConfigurationError) as error:
        database_config.load_database_settings(config(tmp_path))
    assert 'sensitive' not in str(error.value)
