"""Full observability checks with fake providers and temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import logging
from threading import Barrier

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import main, qa_logging, qa_pipeline, recorded_qa
from app.answer_config import AnswerSettings
from app.config import ConfigurationError, Settings
from app.facet_policy import POLICY_VERSION
from app.lightrag_client import UpstreamError
from app.schemas import AskResponse


@pytest.fixture
def captured(monkeypatch):
    output = StringIO()
    logger = logging.Logger('offline_observability', level=logging.INFO)
    logger.addHandler(logging.StreamHandler(output))
    monkeypatch.setattr(qa_logging, 'logger', logger)
    return lambda: [json.loads(line) for line in output.getvalue().splitlines()]


def test_context_is_inherited_and_reset_after_exception(captured):
    with pytest.raises(RuntimeError):
        with qa_logging.qa_log_context(request_id='record', attempt_id='attempt'):
            qa_logging.log_qa_event('inside', None)
            raise RuntimeError('private-error')
    qa_logging.log_qa_event('outside', None)
    inside, outside = captured()
    assert inside['request_id'] == 'record' and inside['attempt_id'] == 'attempt'
    assert outside['request_id'] is None and 'attempt_id' not in outside


def test_context_is_isolated_between_concurrent_threads(captured):
    barrier = Barrier(2)
    def worker(name):
        with qa_logging.qa_log_context(request_id=name, attempt_id='attempt-'+name):
            barrier.wait(timeout=5)
            qa_logging.log_qa_event('parallel', None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, ['one', 'two']))
    assert {(row['request_id'], row['attempt_id']) for row in captured()} == {('one','attempt-one'), ('two','attempt-two')}


def test_failed_stage_records_safe_type_and_preserves_exception(captured):
    original = UpstreamError(504, 'private-error', stage='回答模型')
    with pytest.raises(UpstreamError) as caught:
        with qa_logging.qa_stage('回答模型'):
            raise original
    assert caught.value is original
    started, failed = captured()
    assert started['event'] == 'stage_started'
    assert failed['event'] == 'stage_failed' and failed['http_status'] == 504
    assert failed['duration_ms'] >= 0
    assert 'private-error' not in json.dumps(captured())


def test_logging_failure_does_not_change_business_execution(monkeypatch):
    class BrokenLogger:
        def info(self, *args):
            raise OSError('disk full')
    monkeypatch.setattr(qa_logging, 'logger', BrokenLogger())
    with qa_logging.qa_stage('test'):
        qa_logging.log_qa_event('test', None)


def run(engine, answer_fn, key=None):
    return recorded_qa.run_recorded_qa(engine, question='private-question', corpus_id='test', answer_fn=answer_fn, idempotency_key=key)


def test_record_lifecycle_logs_committed_success_and_replay_separately(record_engine, captured):
    key = '83f28373-e713-4e7f-96ba-ad2c0395175f'
    answer = AskResponse(response='private-answer', references=[], llm_generated=False)
    record_id, _ = run(record_engine, lambda: answer, key)
    def forbidden():
        pytest.fail('Replay must not regenerate')
    run(record_engine, forbidden, key)
    logs = captured()
    events = [row['event'] for row in logs]
    assert events.count('qa_started') == 1
    assert events.count('record_saved') == 1
    assert 'record_reused' in events and 'replay_completed' in events
    assert events.index('record_saved') < events.index('qa_completed')
    assert next(row for row in logs if row['event'] == 'record_saved')['duration_ms'] >= 0
    assert all(row['request_id'] == record_id for row in logs if row['event'] != 'record_create_started')
    assert len({row['attempt_id'] for row in logs}) == 2
    assert not any(value in json.dumps(logs) for value in ['private-question', 'private-answer', key])


def test_model_failure_and_failure_persistence_are_distinguishable(record_engine, captured):
    def fail():
        raise UpstreamError(504, 'private-provider-detail', stage='回答模型')
    with pytest.raises(recorded_qa.RecordedQAError):
        run(record_engine, fail)
    logs = captured()
    events = [row['event'] for row in logs]
    assert 'qa_failed' in events and 'record_saved' in events
    assert 'qa_completed' not in events
    assert next(row for row in logs if row['event'] == 'qa_failed')['http_status'] == 504
    assert 'private-provider-detail' not in json.dumps(logs)


def test_answer_save_failure_never_logs_qa_completed(record_engine, captured, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-db-detail')
    monkeypatch.setattr(recorded_qa, 'save_completed_record', fail)
    with pytest.raises(recorded_qa.RecordedQAError):
        run(record_engine, lambda: AskResponse(response='private-answer', references=[], llm_generated=False))
    events = [row['event'] for row in captured()]
    assert 'answer_ready' in events and 'record_save_failed' in events
    assert next(row for row in captured() if row['event'] == 'record_save_failed')['duration_ms'] >= 0
    assert 'record_saved' not in events and 'qa_completed' not in events
    assert 'private-db-detail' not in json.dumps(captured())


def test_record_create_failure_has_attempt_id_without_fabricated_record_id(record_engine, captured, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-db-detail')
    monkeypatch.setattr(recorded_qa, 'create_processing_record', fail)
    with pytest.raises(recorded_qa.RecordedQAError):
        run(record_engine, lambda: pytest.fail('Must not generate'))
    failure = next(row for row in captured() if row['event'] == 'record_create_failed')
    assert failure['request_id'] is None and failure['attempt_id']
    assert 'private-db-detail' not in json.dumps(captured())


def medium_pipeline(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return qa_pipeline.run_medium_qa_pipeline('private-question', client,
            Settings('http://rag.test','private-key'),
            AnswerSettings('https://answer.test/chat/completions','test','private-key'))


def retrieval(strategy='whole_query_rerank', chunks=True):
    return httpx.Response(200, json={'status':'success', 'data':{'chunks':[
        {'chunk_id':'A', 'reference_id':'1', 'file_path':'test.md', 'content':'private-evidence'}
    ] if chunks else []}, 'metadata':{'doctrace_policy':{'version':POLICY_VERSION, 'strategy':strategy}}})


def test_medium_stages_inherit_record_identity_and_do_not_log_body(record_engine, captured):
    def handler(request):
        if request.url.host == 'rag.test':
            return retrieval('fallback_original')
        return httpx.Response(200, json={'choices':[{'message':{'role':'assistant', 'content':'private-answer [1]'}, 'finish_reason':'stop'}]})
    record_id, _ = run(record_engine, lambda: medium_pipeline(handler))
    logs = captured()
    started = [row['stage'] for row in logs if row['event'] == 'stage_started']
    assert started == ['检索', '检索策略', '上下文组装', '回答模型']
    assert all(row['request_id'] == record_id for row in logs if row['event'].startswith('stage_'))
    policy = next(row for row in logs if row['event'] == 'retrieval_ready')
    assert policy['degraded'] is True and policy['strategy'] == 'fallback_original'
    assert policy['chunk_count'] == 1
    assert not any(value in json.dumps(logs) for value in ['private-question', 'private-evidence', 'private-answer', 'private-key'])


def test_retrieval_timeout_logs_failed_stage_without_model_call(captured):
    def handler(request):
        assert request.url.host == 'rag.test'
        raise httpx.ReadTimeout('private-timeout', request=request)
    with pytest.raises(UpstreamError):
        medium_pipeline(handler)
    failures = [row for row in captured() if row['event'] == 'stage_failed']
    assert len(failures) == 1
    assert failures[0]['stage'] == '检索' and failures[0]['http_status'] == 504
    assert 'private-timeout' not in json.dumps(captured())


def test_empty_evidence_logs_refusal_without_model_stage(captured):
    def handler(request):
        assert request.url.host == 'rag.test'
        return retrieval(chunks=False)
    assert medium_pipeline(handler).llm_generated is False
    assert any(row['event'] == 'evidence_insufficient' for row in captured())
    assert not any(row.get('stage') == '回答模型' for row in captured())


def test_invalid_http_request_has_attempt_id_and_422_but_no_body(captured):
    with TestClient(main.app) as client:
        response = client.post('/ask/optimized', json={'question':'   '}, headers={'Idempotency-Key':'invalid-private-key'})
    assert response.status_code == 422
    logs = captured()
    received = next(row for row in logs if row['event'] == 'http_received')
    ended = next(row for row in logs if row['event'] == 'http_completed')
    assert received['attempt_id'] == ended['attempt_id']
    assert ended['http_status'] == 422 and ended['request_id'] is None
    assert 'invalid-private-key' not in json.dumps(logs)


def test_configuration_failure_is_logged_without_secrets(captured, monkeypatch):
    def fail():
        raise ConfigurationError('private-config-secret')
    monkeypatch.setattr(main, 'load_medium_settings', fail)
    with TestClient(main.app) as client:
        assert client.post('/ask/optimized', json={'question':'private-question'}).status_code == 503
    assert any(row['event'] == 'configuration_failed' for row in captured())
    assert not any(value in json.dumps(captured()) for value in ['private-question','private-config-secret'])
