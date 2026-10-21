from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main, auth_http
from app.auth_schemas import CurrentUserResponse
from app.config import ConfigurationError, Settings
from app.medium_config import MediumSettings
from app.schemas import MediumAskResponse


@pytest.fixture
def api(monkeypatch, record_engine):
    calls = []
    original = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[main.read_current_user] = lambda: CurrentUserResponse(
        user_id='00000000-0000-4000-8000-000000000001', username='tester')
    monkeypatch.setattr(auth_http, 'require_trusted_json', lambda request: None)
    monkeypatch.setattr(main, 'create_db_engine', lambda settings: record_engine)
    monkeypatch.setattr(main, 'load_medium_settings', lambda: MediumSettings(Settings('http://rag.test', 'dummy'), 40000, 'synthetic'))
    monkeypatch.setattr(main, 'load_answer_settings', lambda: object())
    monkeypatch.setattr(main, 'load_pipeline_settings', lambda: object(), raising=False)
    monkeypatch.setattr(main, 'load_rerank_settings', lambda: object(), raising=False)
    monkeypatch.setattr(main, 'make_qa_client', lambda: nullcontext(object()))
    def answer(*args, mode, **kwargs):
        calls.append(mode)
        return MediumAskResponse(response='Synthetic answer', references=[], llm_generated=False,
            retrieval={'mode':mode, 'policy_version':'synthetic', 'strategy':'synthetic', 'degraded':False})
    monkeypatch.setattr(main, 'run_selected_qa_pipeline', answer, raising=False)
    try:
        with TestClient(main.app) as client:
            yield client, calls, record_engine
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original)


@pytest.mark.parametrize('mode', ['naive', 'mix', None])
def test_route_uses_and_saves_selected_mode(api, mode):
    client, calls, engine = api
    body = {'question':'Question'}
    if mode is not None:
        body['mode'] = mode
    response = client.post('/ask/optimized', json=body)
    expected = mode or 'naive'
    assert response.status_code == 200
    assert calls == [expected] and response.json()['retrieval']['mode'] == expected
    with engine.connect() as connection:
        assert connection.execute(text('SELECT request_mode FROM qa_records')).scalar_one() == expected


def test_route_rejects_changed_mode_with_same_key(api):
    client, calls, _ = api
    headers = {'Idempotency-Key':'00000000-0000-4000-8000-000000000002'}
    first = client.post('/ask/optimized', json={'question':'Question', 'mode':'naive'}, headers=headers)
    second = client.post('/ask/optimized', json={'question':'Question', 'mode':'mix'}, headers=headers)
    assert first.status_code == 200 and second.status_code == 409 and calls == ['naive']


def test_invalid_mode_stops_before_generation(api):
    client, calls, _ = api
    assert client.post('/ask/optimized', json={'question':'Question', 'mode':'auto'}).status_code == 422
    assert calls == []


def test_naive_config_failure_is_safe_503_before_record_creation(api, monkeypatch):
    client, calls, engine = api
    def broken():
        raise ConfigurationError('private-value')
    monkeypatch.setattr(main, 'load_rerank_settings', broken, raising=False)
    response = client.post('/ask/optimized', json={'question':'Question', 'mode':'naive'})
    assert response.status_code == 503 and 'private-value' not in response.text
    assert calls == []
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one() == 0
