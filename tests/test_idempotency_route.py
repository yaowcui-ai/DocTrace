"""HTTP idempotency against temporary SQLite, with a fake answer service."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main
from app.answer_config import AnswerSettings
from app.config import Settings
from app.lightrag_client import UpstreamError
from app.medium_config import MediumSettings
from app.qa_records import create_processing_record, get_qa_record
from app.schemas import MediumAskResponse

KEY = '6c394439-e0da-4832-8da9-663f947406f9'


@pytest.fixture
def api(monkeypatch, record_engine):
    calls = []
    monkeypatch.setattr(main, 'create_db_engine', lambda settings: record_engine)
    monkeypatch.setattr(main, 'load_medium_settings', lambda: MediumSettings(Settings('http://rag.test', 'dummy'), 40000, 'test_corpus'))
    monkeypatch.setattr(main, 'load_answer_settings', lambda: AnswerSettings('https://answer.test/chat/completions', 'dummy', 'dummy'))
    monkeypatch.setattr(main, 'make_qa_client', lambda: nullcontext(object()))
    def generate(*args, **kwargs):
        calls.append('answer')
        return MediumAskResponse(response='离线答案', references=[], llm_generated=False)
    monkeypatch.setattr(main, 'run_selected_qa_pipeline', generate)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, engine=record_engine, calls=calls)


def post(api, key=KEY, question='测试问题'):
    headers = {} if key is None else {'Idempotency-Key': key}
    return api.client.post('/ask/optimized', json={'question':question, 'mode':'mix'}, headers=headers)


def count(api):
    with api.engine.connect() as conn:
        return conn.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one()


def test_header_key_is_persisted(api):
    response = post(api)
    assert response.status_code == 200
    with api.engine.connect() as conn:
        assert conn.execute(text('SELECT idempotency_key FROM qa_records')).scalar_one() == KEY
    assert api.calls == ['answer']


def test_same_key_returns_same_id_and_answer_without_regeneration(api):
    first = post(api)
    second = post(api)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert count(api) == 1
    assert api.calls == ['answer']


def test_processing_key_returns_409_and_original_id(api):
    original = create_processing_record(api.engine, owner_user_id="00000000-0000-4000-8000-000000000001", question='测试问题', corpus_id='test_corpus', idempotency_key=KEY)
    response = post(api)
    assert response.status_code == 409
    assert response.json()['detail']['request_id'] == original
    assert response.json()['detail']['stage'] == '请求状态'
    assert get_qa_record(api.engine, original)['status'] == 'processing'
    assert api.calls == []


def test_failed_key_replays_error_without_second_pipeline_call(api, monkeypatch):
    def timeout(*args, **kwargs):
        api.calls.append('answer')
        raise UpstreamError(504, '离线模拟超时', stage='回答模型')
    monkeypatch.setattr(main, 'run_selected_qa_pipeline', timeout)
    first = post(api)
    second = post(api)
    assert first.status_code == second.status_code == 504
    assert first.json() == second.json()
    assert count(api) == 1
    assert api.calls == ['answer']


def test_same_key_different_question_is_a_conflict(api):
    first = post(api)
    second = post(api, question='另一个问题')
    assert second.status_code == 409
    assert second.json()['detail']['stage'] == '请求校验'
    assert second.json()['detail']['request_id'] == first.json()['request_id']
    assert count(api) == 1
    assert api.calls == ['answer']


@pytest.mark.parametrize('key', ['', 'not-a-uuid', '123', KEY+'x'])
def test_invalid_header_is_rejected_before_insert_or_generation(api, key):
    assert post(api, key=key).status_code == 422
    assert count(api) == 0
    assert api.calls == []


def test_equivalent_uuid_spelling_uses_one_canonical_key(api):
    first = post(api, key=KEY.upper())
    second = post(api)
    assert first.status_code == second.status_code == 200
    assert first.json()['request_id'] == second.json()['request_id']
    assert count(api) == 1
    assert api.calls == ['answer']


def test_legacy_requests_without_header_still_create_new_operations(api):
    first = post(api, key=None)
    second = post(api, key=None)
    assert first.status_code == second.status_code == 200
    assert first.json()['request_id'] != second.json()['request_id']
    assert count(api) == 2
    assert api.calls == ['answer', 'answer']
