from pathlib import Path

import pytest

from app.config import ConfigurationError, load_settings
from app import medium_config


@pytest.fixture(autouse=True)
def clear_environment(monkeypatch):
    for key in ('LIGHTRAG_URL','LIGHTRAG_API_KEY','HR_LIGHTRAG_URL','HR_MAX_TOTAL_TOKENS','HR_CORPUS_ID'):
        monkeypatch.delenv(key,raising=False)


def config(tmp_path, **updates):
    values={'LIGHTRAG_URL':'http://127.0.0.1:9622','HR_LIGHTRAG_URL':'http://127.0.0.1:9624',
            'LIGHTRAG_API_KEY':'service-key','HR_MAX_TOTAL_TOKENS':'40000','HR_CORPUS_ID':'gitlab_hr_v3'}
    values.update(updates)
    path=tmp_path/'.env'
    path.write_text('\n'.join(k+'='+v for k,v in values.items() if v is not None),encoding='utf-8')
    return path


def test_medium_and_legacy_addresses_are_selected_independently(tmp_path):
    path=config(tmp_path)
    medium=medium_config.load_medium_settings(path)
    assert medium.rag_settings.lightrag_url=='http://127.0.0.1:9624'
    assert medium.rag_settings.lightrag_api_key=='service-key'
    assert medium.max_total_tokens==40000
    assert medium.corpus_id=='gitlab_hr_v3'
    assert load_settings(path).lightrag_url=='http://127.0.0.1:9622'


def test_medium_environment_overrides_file(tmp_path,monkeypatch):
    monkeypatch.setenv('HR_MAX_TOTAL_TOKENS','41000')
    assert medium_config.load_medium_settings(config(tmp_path)).max_total_tokens==41000


def test_missing_medium_address_does_not_fall_back_to_old_library(tmp_path):
    with pytest.raises(ConfigurationError):medium_config.load_medium_settings(config(tmp_path,HR_LIGHTRAG_URL=None))


@pytest.mark.parametrize('url',['file:///private','http://user:secret@localhost:9624','http://localhost:9624?secret=1'])
def test_invalid_medium_address_is_rejected(tmp_path,url):
    with pytest.raises(ConfigurationError):medium_config.load_medium_settings(config(tmp_path,HR_LIGHTRAG_URL=url))


@pytest.mark.parametrize('budget',[None,'','0','-1','1.5','true'])
def test_invalid_token_budget_is_rejected(tmp_path,budget):
    with pytest.raises(ConfigurationError):medium_config.load_medium_settings(config(tmp_path,HR_MAX_TOTAL_TOKENS=budget))


@pytest.mark.parametrize('value',[None,'',' ','x'*65,'bad/name','bad\x01value'])
def test_invalid_corpus_identifier_is_rejected(tmp_path, value):
    with pytest.raises(ConfigurationError):
        medium_config.load_medium_settings(config(tmp_path,HR_CORPUS_ID=value))


def test_corpus_identifier_environment_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv('HR_CORPUS_ID','test_corpus_v2')
    assert medium_config.load_medium_settings(config(tmp_path)).corpus_id=='test_corpus_v2'
