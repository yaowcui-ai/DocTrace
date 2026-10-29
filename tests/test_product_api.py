"""Offline product contracts: real SQLite persistence, zero provider calls."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import auth_http
from app.auth_config import AuthSettings
from app.auth_routes import read_current_user
from app.auth_schemas import CurrentUserResponse
from app.lightrag_client import UpstreamError
from app.qa_records import create_processing_record, save_failed_record
from app.recorded_qa import RecordedQAError, run_recorded_qa
from app.schemas import AskResponse

ALICE = '00000000-0000-4000-8000-000000000001'
BOB = '00000000-0000-4000-8000-000000000002'
ORIGIN = 'http://127.0.0.1:8001'


@pytest.fixture
def product(record_engine, monkeypatch):
    app = FastAPI()
    app.state.db_engine = record_engine
    app.state.product_frozen_corpus_id = 'offline'
    state = SimpleNamespace(owner=ALICE, calls=[], fail=False)
    def identity():
        if state.owner is None:
            raise HTTPException(401, '请先登录。')
        return CurrentUserResponse(user_id=state.owner, username='alice' if state.owner == ALICE else 'bob')
    app.dependency_overrides[read_current_user] = identity
    monkeypatch.setattr(auth_http, 'load_auth_settings', lambda: AuthSettings(ORIGIN, False, 7200))
    def runner(*, request, http_request, user, idempotency_key):
        def answer():
            state.calls.append(request.question)
            if state.fail:
                raise UpstreamError(502, '模型暂时无法完成请求。', stage='回答模型')
            return AskResponse(response='SAVED ANSWER NOT POLICY HISTORY', references=[
                {'reference_id': '1', 'file_path': 'C:/private/source/policy.md', 'content': ['Recorded policy evidence']}
            ], llm_generated=True)
        try:
            rid, result = run_recorded_qa(record_engine, question=request.question, corpus_id='offline',
                answer_fn=answer, owner_user_id=str(user.user_id), idempotency_key=str(idempotency_key), request_mode=request.mode)
        except RecordedQAError as error:
            raise HTTPException(error.status_code, {'message': error.detail, 'request_id': error.request_id})
        return SimpleNamespace(request_id=rid, **result.model_dump())
    from app.product import api, tables
    tables.metadata.create_all(record_engine)
    app.state.product_qa_runner = runner
    app.include_router(api.router)
    with TestClient(app, base_url=ORIGIN) as client:
        client.headers['Origin'] = ORIGIN
        yield client, record_engine, state


def conversation(client, title='Policy conversation'):
    response = client.post('/api/v1/conversations', json={'title': title})
    assert response.status_code == 200, response.text
    return response.json()['data']['id']


def test_history_search_includes_message_questions_and_pages_are_disjoint(product):
    client, _, _ = product
    ids = [conversation(client, 'Same title') for _ in range(3)]
    send(client, ids[0], question='Unique searchable relocation policy')
    found = client.get('/api/v1/conversations?q=relocation').json()['data']['items']
    assert [item['id'] for item in found] == [ids[0]]
    first = client.get('/api/v1/conversations?limit=2').json()['data']
    second = client.get('/api/v1/conversations?limit=2&offset=2').json()['data']
    assert first['has_more'] and not second['has_more']
    assert {item['id'] for item in first['items']}.isdisjoint(item['id'] for item in second['items'])


def test_earlier_message_pages_can_be_loaded_without_losing_history(product):
    client, _, _ = product
    cid = conversation(client)
    for question in ['First question', 'Second question', 'Third question']:
        assert send(client, cid, question=question).status_code == 200
    latest = client.get(f'/api/v1/conversations/{cid}?limit=2').json()['data']
    earlier = client.get(f'/api/v1/conversations/{cid}?limit=2&offset=2').json()['data']
    assert len(latest['messages']) == 2 and latest['has_more']
    assert [item['question'] for item in earlier['messages']] == ['First question']
    assert earlier['has_more'] is False


def send(client, cid, question='Current question', key=None, mode='naive'):
    return client.post(f'/api/v1/conversations/{cid}/messages', json={'question': question, 'mode': mode},
        headers={'Idempotency-Key': key or str(uuid4())})


def test_me_defaults_to_user_and_never_admin(product):
    client, _, _ = product
    response = client.get('/api/v1/me')
    assert response.status_code == 200
    assert response.json()['data'] == {'user_id': ALICE, 'username': 'alice', 'role': 'user'}
    assert response.headers['cache-control'] == 'no-store'


def test_idempotency_key_binds_selected_knowledge_base(product):
    client, engine, state = product
    cid = conversation(client)
    key = str(uuid4())
    first = send(client, cid, key=key)
    assert first.status_code == 200
    changed = client.post(f'/api/v1/conversations/{cid}/messages', json={
        'question': 'Current question', 'mode': 'naive', 'knowledge_base': 'managed'},
        headers={'Idempotency-Key': key})
    assert changed.status_code == 409
    assert len(state.calls) == 1


def test_unknown_knowledge_base_is_rejected_before_model(product):
    client, engine, state = product
    cid = conversation(client)
    result = client.post(f'/api/v1/conversations/{cid}/messages', json={
        'question': 'Question', 'knowledge_base': 'someone_else_secret'},
        headers={'Idempotency-Key': str(uuid4())})
    assert result.status_code == 422 and state.calls == []


def test_imported_history_preserves_original_corpus_and_does_not_invent_actual_mode(product):
    client, engine, state = product
    rid = create_processing_record(engine, question='Legacy original corpus question', corpus_id='old_corpus_v1', owner_user_id=ALICE)
    from app.qa_records import save_completed_record
    save_completed_record(engine, rid, result=AskResponse(response='Old saved answer', references=[], llm_generated=False), duration_ms=1)
    assert client.post('/api/v1/conversations/import-records', json={}).status_code == 200
    cid = client.get('/api/v1/conversations').json()['data']['items'][0]['id']
    message = client.get('/api/v1/conversations/'+cid).json()['data']['messages'][0]
    assert message['corpus_id'] == 'old_corpus_v1'
    assert message['actual_mode'] is None and message['historical_import'] is True


def test_raw_frozen_operation_cannot_be_adopted_as_managed(product):
    client, engine, state = product
    key = str(uuid4())
    run_recorded_qa(engine, question='Same question', corpus_id='offline', answer_fn=lambda: AskResponse(
        response='Frozen answer', references=[], llm_generated=False), owner_user_id=ALICE, idempotency_key=key, request_mode='naive')
    cid = conversation(client)
    response = client.post(f'/api/v1/conversations/{cid}/messages', json={
        'question': 'Same question', 'mode': 'naive', 'knowledge_base': 'managed'}, headers={'Idempotency-Key': key})
    assert response.status_code == 409


def test_import_does_not_take_a_processing_record_reserved_by_a_conversation(product):
    client, engine, state = product
    from app.product import repository as repo
    cid, key = conversation(client), str(uuid4())
    repo.reserve_message(engine, ALICE, cid, 'In flight', 'naive', key, 'In flight', 'current_question_only')
    create_processing_record(engine, question='In flight', corpus_id='offline', owner_user_id=ALICE, idempotency_key=key, request_mode='naive')
    response = client.post('/api/v1/conversations/import-records', json={})
    assert response.status_code == 200
    assert response.json()['data']['imported'] == 0


def test_role_is_read_from_explicit_role_table(product):
    client, engine, _ = product
    from app.product.tables import roles
    with engine.begin() as conn:
        conn.execute(roles.insert().values(user_id=ALICE, role='admin'))
    assert client.get('/api/v1/me').json()['data']['role'] == 'admin'


def test_anonymous_rejected_and_error_not_cached(product):
    client, _, state = product
    state.owner = None
    response = client.get('/api/v1/me')
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'


def test_conversation_search_filters_owner_and_literal_wildcards(product):
    client, _, state = product
    mine = conversation(client, 'Remote 100% rules')
    conversation(client, 'Remote other rules')
    state.owner = BOB
    conversation(client, 'Remote 100% private')
    state.owner = ALICE
    response = client.get('/api/v1/conversations', params={'q': '100%', 'limit': 1})
    assert response.status_code == 200
    assert [item['id'] for item in response.json()['data']['items']] == [mine]
    assert response.json()['data']['has_more'] is False


@pytest.mark.parametrize('query', [{'limit': 101}, {'limit': 0}, {'q': 'x' * 201}])
def test_conversation_search_is_bounded(product, query):
    assert product[0].get('/api/v1/conversations', params=query).status_code == 422


def test_other_users_conversation_is_hidden_before_generation(product):
    client, _, state = product
    cid = conversation(client)
    state.owner = BOB
    assert client.get('/api/v1/conversations/' + cid).status_code == 404
    assert send(client, cid).status_code == 404
    assert state.calls == []


def test_writes_require_trusted_origin_and_json(product):
    client, _, _ = product
    response = client.post('/api/v1/conversations', json={'title': 'x'}, headers={'Origin': 'https://attacker.example'})
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/v1/conversations', content='{}', headers={'Content-Type': 'text/plain'}).status_code == 415


def test_message_key_is_required_and_uuid(product):
    client, _, state = product
    cid = conversation(client)
    url = f'/api/v1/conversations/{cid}/messages'
    assert client.post(url, json={'question': 'x', 'mode': 'naive'}).status_code == 422
    assert client.post(url, json={'question': 'x'}, headers={'Idempotency-Key': 'invalid'}).status_code == 422
    assert state.calls == []


def test_message_replay_returns_same_saved_answer_without_generation(product):
    client, engine, state = product
    cid = conversation(client)
    key = str(uuid4())
    first, second = send(client, cid, key=key), send(client, cid, key=key)
    assert first.status_code == second.status_code == 200
    a, b = first.json()['data'], second.json()['data']
    assert a['request_id'] == b['request_id']
    assert a['id'] == b['id']
    assert a['status'] == 'completed'
    assert a['question'] == 'Current question'
    assert a['references'][0]['file_path'] == 'policy.md'
    assert len(state.calls) == 1
    from app.product.tables import messages
    with engine.connect() as conn:
        assert len(conn.execute(select(messages)).all()) == 1
    detail = client.get('/api/v1/conversations/' + cid).json()['data']
    assert detail['messages'][0]['answer'] == a['answer']


def test_same_operation_key_cannot_move_between_conversations(product):
    client, _, state = product
    first, second = conversation(client), conversation(client)
    key = str(uuid4())
    assert send(client, first, key=key).status_code == 200
    assert send(client, second, key=key).status_code == 409
    assert len(state.calls) == 1


@pytest.mark.parametrize('question,mode', [('Changed', 'naive'), ('Current question', 'mix')])
def test_same_operation_key_cannot_change_payload(product, question, mode):
    client, _, state = product
    cid, key = conversation(client), str(uuid4())
    assert send(client, cid, key=key).status_code == 200
    assert send(client, cid, question, key, mode).status_code == 409
    assert len(state.calls) == 1


@pytest.mark.parametrize('failed', [False, True])
def test_existing_qa_processing_or_failed_record_is_associated_without_regeneration(product, failed):
    client, engine, state = product
    cid, key = conversation(client), str(uuid4())
    rid = create_processing_record(engine, question='Current question', corpus_id='offline',
        owner_user_id=ALICE, idempotency_key=key, request_mode='naive')
    if failed:
        save_failed_record(engine, rid, error=UpstreamError(502, 'Stored failure'), duration_ms=0)
    response = send(client, cid, key=key)
    assert response.status_code == 200
    assert response.json()['data']['request_id'] == rid
    assert response.json()['data']['status'] == ('failed' if failed else 'processing')
    assert state.calls == []


def test_context_expansion_is_bounded_questions_only_and_persisted_for_replay(product):
    client, _, state = product
    cid = conversation(client)
    for question in ['HISTORY ZERO', 'HISTORY ONE', 'HISTORY TWO']:
        assert send(client, cid, question).status_code == 200
    key = str(uuid4())
    response = send(client, cid, 'CURRENT EXACT', key)
    assert response.status_code == 200
    message = response.json()['data']
    query = state.calls[-1]
    assert 'HISTORY ZERO' not in query
    assert 'HISTORY ONE' in query and 'HISTORY TWO' in query and 'CURRENT EXACT' in query
    assert 'SAVED ANSWER NOT POLICY HISTORY' not in query
    assert message['query_text'] == query
    assert message['context_method'] == 'last_two_user_questions_v1'
    assert send(client, cid, 'LATER QUESTION').status_code == 200
    count = len(state.calls)
    assert send(client, cid, 'CURRENT EXACT', key).json()['data']['id'] == message['id']
    assert len(state.calls) == count


def test_citation_is_exact_owned_recorded_content_without_disk_read(product):
    client, _, state = product
    cid = conversation(client)
    rid = send(client, cid).json()['data']['request_id']
    citation = client.get(f'/api/v1/citations/{rid}/1')
    assert citation.status_code == 200
    assert citation.json()['data'] == {'reference_id': '1', 'file_path': 'policy.md', 'content': ['Recorded policy evidence']}
    assert client.get(f'/api/v1/citations/{rid}/01').status_code == 404
    state.owner = BOB
    assert client.get(f'/api/v1/citations/{rid}/1').status_code == 404


def test_feedback_upserts_owned_completed_message_and_rejects_other_user(product):
    client, engine, state = product
    cid = conversation(client)
    rid = send(client, cid).json()['data']['request_id']
    url = f'/api/v1/messages/{rid}/feedback'
    assert client.put(url, json={'helpful': True, 'comment': 'Useful'}).status_code == 200
    assert client.put(url, json={'helpful': False, 'comment': 'Correction'}).status_code == 200
    from app.product.tables import feedback
    with engine.connect() as conn:
        rows = conn.execute(select(feedback)).mappings().all()
    assert len(rows) == 1 and rows[0]['helpful'] is False and rows[0]['comment'] == 'Correction'
    state.owner = BOB
    assert client.put(url, json={'helpful': True}).status_code == 404


def test_feedback_rejects_processing_and_orphan_qa_records(product):
    client, engine, _ = product
    rid = create_processing_record(engine, question='x', corpus_id='offline', owner_user_id=ALICE)
    assert client.put(f'/api/v1/messages/{rid}/feedback', json={'helpful': True}).status_code == 404
    cid, key = conversation(client), str(uuid4())
    rid = create_processing_record(engine, question='Current question', corpus_id='offline',
        owner_user_id=ALICE, idempotency_key=key, request_mode='naive')
    assert send(client, cid, key=key).status_code == 200
    assert client.put(f'/api/v1/messages/{rid}/feedback', json={'helpful': True}).status_code == 409


def test_database_errors_are_sanitized(product, monkeypatch):
    client, engine, _ = product
    from sqlalchemy.exc import SQLAlchemyError
    def fail(*args, **kwargs):
        raise SQLAlchemyError('sensitive database credentials')
    monkeypatch.setattr(engine, 'connect', fail)
    response = client.get('/api/v1/conversations')
    assert response.status_code == 503
    assert 'sensitive' not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_runner_failure_keeps_association_and_retry_does_not_regenerate(product):
    client, _, state = product
    cid, key = conversation(client), str(uuid4())
    state.fail = True
    first = send(client, cid, key=key)
    assert first.status_code == 502
    second = send(client, cid, key=key)
    assert second.status_code == 200
    assert second.json()['data']['status'] == 'failed'
    assert len(state.calls) == 1


def test_role_dependency_refuses_regular_user_and_allows_explicit_admin(product):
    client, engine, _ = product
    from fastapi import APIRouter, Depends
    from app.product.api import ProductRoute, require_admin
    from app.product.tables import roles
    probe_router = APIRouter(route_class=ProductRoute)
    @probe_router.get('/admin-probe', dependencies=[Depends(require_admin)])
    def probe():
        return {'ok': True}
    client.app.include_router(probe_router)
    assert client.get('/admin-probe').status_code == 403
    with engine.begin() as conn:
        conn.execute(roles.insert().values(user_id=ALICE, role='admin'))
    assert client.get('/admin-probe').status_code == 200


def test_feedback_needs_actual_owned_qa_not_only_cached_message_status(product):
    client, engine, _ = product
    cid = conversation(client)
    rid = send(client, cid).json()['data']['request_id']
    with engine.begin() as conn:
        conn.execute(text('UPDATE qa_records SET owner_user_id=:owner WHERE request_id=:rid'), {'owner': BOB, 'rid': rid})
    response = client.put(f'/api/v1/messages/{rid}/feedback', json={'helpful': True})
    assert response.status_code == 404


def test_conversation_messages_expose_saved_feedback_after_reload(product):
    client, _, _ = product
    cid = conversation(client)
    rid = send(client, cid).json()['data']['request_id']
    client.put(f'/api/v1/messages/{rid}/feedback', json={'helpful': False, 'comment': 'Need more evidence'})
    message = client.get('/api/v1/conversations/' + cid).json()['data']['messages'][0]
    assert message['feedback']['helpful'] is False
    assert message['feedback']['comment'] == 'Need more evidence'


def test_default_runner_calls_existing_orchestrator_with_explicit_parameters(product, monkeypatch):
    client, _, state = product
    from app import main
    runner = client.app.state.product_qa_runner
    del client.app.state.product_qa_runner
    monkeypatch.setattr(main, 'ask_optimized', runner)
    response = send(client, conversation(client), question='Production adapter')
    assert response.status_code == 200
    assert state.calls == ['Production adapter']


def test_import_legacy_records_preserves_qa_is_owned_and_idempotent(product):
    client, engine, state = product
    mine = create_processing_record(engine, question='Legacy policy question', corpus_id='offline', owner_user_id=ALICE)
    create_processing_record(engine, question='Other user private record', corpus_id='offline', owner_user_id=BOB)
    create_processing_record(engine, question='Unassigned record', corpus_id='offline')
    with engine.connect() as conn:
        before = [dict(row) for row in conn.execute(text('SELECT * FROM qa_records ORDER BY request_id')).mappings()]
    first = client.post('/api/v1/conversations/import-records', json={})
    assert first.status_code == 200
    assert first.json()['data']['imported'] == 1
    assert client.post('/api/v1/conversations/import-records', json={}).json()['data']['imported'] == 0
    convs = client.get('/api/v1/conversations').json()['data']['items']
    assert len(convs) == 1 and convs[0]['title'] == 'Legacy policy question'
    message = client.get('/api/v1/conversations/' + convs[0]['id']).json()['data']['messages'][0]
    assert message['request_id'] == mine
    assert message['query_text'] == 'Legacy policy question' and message['context_method'] == 'legacy_import'
    with engine.connect() as conn:
        after = [dict(row) for row in conn.execute(text('SELECT * FROM qa_records ORDER BY request_id')).mappings()]
    assert before == after
    assert state.calls == []


def test_import_skips_associated_records_and_limits_each_batch(product):
    client, engine, _ = product
    cid = conversation(client)
    send(client, cid)
    for index in range(3):
        create_processing_record(engine, question='Legacy ' + str(index), corpus_id='offline', owner_user_id=ALICE)
    first = client.post('/api/v1/conversations/import-records?limit=2', json={})
    assert first.status_code == 200
    assert first.json()['data']['imported'] == 2
    assert first.json()['data']['has_more'] is True
    second = client.post('/api/v1/conversations/import-records?limit=2', json={})
    assert second.json()['data']['imported'] == 1
    assert second.json()['data']['has_more'] is False


def test_imported_qa_operation_cannot_be_reassociated_to_new_conversation(product):
    client, engine, state = product
    key = str(uuid4())
    create_processing_record(engine, question='Current question', corpus_id='offline', owner_user_id=ALICE,
        idempotency_key=key, request_mode='naive')
    assert client.post('/api/v1/conversations/import-records', json={}).status_code == 200
    new_conversation = conversation(client)
    assert send(client, new_conversation, key=key).status_code == 409
    assert state.calls == []
