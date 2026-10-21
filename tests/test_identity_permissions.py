"""Offline end-to-end access control, with two users and zero provider calls."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth_config import AuthSettings, SESSION_COOKIE_NAME
from app.qa_records import create_processing_record, save_completed_record
from app.recorded_qa import run_recorded_qa
from app.schemas import AskResponse
from app.sessions import create_session, get_session_user
from app.users import create_user


@pytest.fixture
def secured(session_engine, monkeypatch):
    from app import main, auth_http
    with session_engine.begin() as conn:
        conn.execute(text('''CREATE TABLE qa_records (
            request_id CHAR(36) PRIMARY KEY, owner_user_id CHAR(36),
            idempotency_key CHAR(36), question TEXT NOT NULL, corpus_id TEXT NOT NULL,
            request_mode TEXT NOT NULL DEFAULT 'mix',
            status TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
            answer TEXT, references_json TEXT, retrieval_json TEXT, http_status INTEGER,
            llm_generated INTEGER, duration_ms INTEGER, error_stage TEXT, error_message TEXT,
            UNIQUE(owner_user_id, idempotency_key),
            FOREIGN KEY(owner_user_id) REFERENCES app_users(user_id)
        )'''))
        conn.execute(text('CREATE UNIQUE INDEX legacy_keys ON qa_records(idempotency_key) WHERE owner_user_id IS NULL'))
    alice = create_user(session_engine, username='alice', password='Al1ce!23')
    bob = create_user(session_engine, username='bob', password='B0b!1234')
    token_a, _ = create_session(session_engine, user_id=alice)
    token_b, _ = create_session(session_engine, user_id=bob)
    monkeypatch.setattr(main, 'create_db_engine', lambda settings: session_engine)
    monkeypatch.setattr(auth_http, 'load_auth_settings', lambda: AuthSettings('http://127.0.0.1:8001', False, 7200))
    def forbidden(*args, **kwargs):
        pytest.fail('A permissions test attempted to call a provider')
    monkeypatch.setattr(main, 'make_qa_client', forbidden)
    monkeypatch.setattr(main.LightRAGClient, 'ask', forbidden)
    with TestClient(main.app, base_url='http://127.0.0.1:8001') as client:
        client.headers['Origin'] = 'http://127.0.0.1:8001'
        yield client, session_engine, alice, bob, token_a, token_b


def answer():
    return AskResponse(response='Synthetic permission test', references=[], llm_generated=False)


def record(engine, owner=None, key=None):
    rid = create_processing_record(engine, question='synthetic', corpus_id='test', owner_user_id=owner, idempotency_key=key)
    save_completed_record(engine, rid, result=answer(), duration_ms=0)
    return rid


@pytest.mark.parametrize('method,path', [('GET','/records'), ('GET','/records/'+str(uuid4())), ('POST','/ask'), ('POST','/ask/optimized')])
def test_anonymous_is_denied_before_provider(secured, method, path):
    client, *_ = secured
    response = client.request(method, path, json={'question':'test'} if method == 'POST' else None)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


def test_history_is_filtered_before_pagination_and_foreign_ids_are_hidden(secured):
    client, engine, alice, bob, token_a, _ = secured
    mine = record(engine, alice)
    theirs = record(engine, bob)
    legacy = record(engine)
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    response = client.get('/records?limit=1&offset=0')
    assert response.status_code == 200
    assert [item['request_id'] for item in response.json()['items']] == [mine]
    assert response.json()['has_more'] is False
    assert client.get('/records/'+mine).status_code == 200
    assert client.get('/records/'+theirs).status_code == 404
    assert client.get('/records/'+legacy).status_code == 404


def test_same_key_isolated_between_accounts_and_replay_remains_local(secured):
    _, engine, alice, bob, *_ = secured
    key = str(uuid4())
    aid, _ = run_recorded_qa(engine, question='a', corpus_id='test', answer_fn=answer, idempotency_key=key, owner_user_id=alice)
    bid, _ = run_recorded_qa(engine, question='b', corpus_id='test', answer_fn=answer, idempotency_key=key, owner_user_id=bob)
    assert aid != bid
    def no_repeat():
        pytest.fail('Idempotency replay executed answer generation')
    assert run_recorded_qa(engine, question='a', corpus_id='test', answer_fn=no_repeat, idempotency_key=key, owner_user_id=alice)[0] == aid


def test_logout_revokes_server_session_and_cookie(secured):
    client, engine, _, _, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    response = client.post('/auth/logout', json={})
    assert response.status_code == 204
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert get_session_user(engine, token_a) is None
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    assert client.get('/records').status_code == 401


@pytest.mark.parametrize('path', ['/ask','/ask/optimized','/auth/logout'])
def test_unsafe_cross_origin_is_denied(secured, path):
    client, _, _, _, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    assert client.post(path, json={'question':'x'}, headers={'Origin':'https://attacker.example'}).status_code == 403


def test_expired_session_does_not_read_history(secured):
    client, engine, _, _, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    with engine.begin() as conn:
        conn.execute(text("UPDATE app_sessions SET created_at='2000-01-01',expires_at='2000-01-02'"))
    assert client.get('/records').status_code == 401


def test_http_qa_assigns_server_identity_and_replays_without_model(secured, monkeypatch):
    from app import main
    from types import SimpleNamespace
    client, engine, alice, bob, token_a, token_b = secured
    key = str(uuid4())
    mine = record(engine, alice, key)
    theirs = record(engine, bob, key)
    monkeypatch.setattr(main, 'load_medium_settings', lambda: SimpleNamespace(corpus_id='test'))
    monkeypatch.setattr(main, 'load_answer_settings', lambda: None)
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    r = client.post('/ask/optimized', json={'question':'synthetic', 'mode':'mix'}, headers={'Idempotency-Key':key})
    assert r.status_code == 200
    assert r.json()['request_id'] == mine
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, token_b)
    r = client.post('/ask/optimized', json={'question':'synthetic', 'mode':'mix'}, headers={'Idempotency-Key':key})
    assert r.status_code == 200
    assert r.json()['request_id'] == theirs


def test_new_http_question_is_owned_by_cookie_not_payload(secured, monkeypatch):
    from app import main
    from types import SimpleNamespace
    from contextlib import nullcontext
    client, engine, alice, _, token_a, _ = secured
    monkeypatch.setattr(main, 'load_medium_settings', lambda: SimpleNamespace(corpus_id='test',rag_settings=None,max_total_tokens=40000))
    monkeypatch.setattr(main, 'load_answer_settings', lambda: None)
    monkeypatch.setattr(main, 'make_qa_client', lambda: nullcontext(None))
    monkeypatch.setattr(main, 'run_selected_qa_pipeline', lambda *args, **kwargs: answer())
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    response=client.post('/ask/optimized',json={'question':'synthetic new', 'mode':'mix'})
    assert response.status_code == 200
    with engine.connect() as conn:
        assert conn.execute(text('SELECT owner_user_id FROM qa_records WHERE request_id=:id'),{'id':response.json()['request_id']}).scalar_one() == alice
    assert client.post('/ask/optimized',json={'question':'synthetic','owner_user_id':'injected'}).status_code == 422


def test_stale_tab_identity_is_denied_before_paid_work(secured):
    client, _, _, bob, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    response = client.post('/ask/optimized',json={'question':'test'},headers={'X-DocTrace-User-ID':bob})
    assert response.status_code == 409
    assert response.headers['X-DocTrace-Identity-Changed'] == '1'


def test_logout_database_error_does_not_claim_revocation(secured, monkeypatch):
    from app import auth_routes
    from sqlalchemy.exc import SQLAlchemyError
    client, engine, _, _, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-db-details')
    monkeypatch.setattr(auth_routes,'revoke_session',fail)
    response=client.post('/auth/logout',json={})
    assert response.status_code == 503
    assert 'set-cookie' not in response.headers
    assert 'private-db-details' not in response.text
    assert get_session_user(engine,token_a) is not None


def test_logout_only_revokes_current_session(secured):
    client, engine, alice, _, token_a, _ = secured
    other_token,_=create_session(engine,user_id=alice)
    client.cookies.set(SESSION_COOKIE_NAME, token_a)
    assert client.post('/auth/logout',json={}).status_code == 204
    assert get_session_user(engine,other_token) is not None
    client.cookies.clear()
    assert client.post('/auth/logout',json={}).status_code == 204


@pytest.mark.parametrize('origin', [None, 'null', 'http://127.0.0.1:8001.attacker.example'])
def test_missing_or_untrusted_origin_cannot_submit_question(secured, origin):
    client, _, _, _, token_a, _ = secured
    client.cookies.set(SESSION_COOKIE_NAME,token_a)
    client.headers.pop('Origin',None)
    headers={} if origin is None else {'Origin':origin}
    assert client.post('/ask/optimized',json={'question':'synthetic', 'mode':'mix'},headers=headers).status_code == 403
