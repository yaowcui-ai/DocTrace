"""Offline saved-result replay checks; no database credentials or model calls."""
import json
from copy import deepcopy

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import recorded_qa

RECORD_ID = '0ea2dc6b-2a50-4e7c-a496-12ca2f08f478'


@pytest.fixture
def saved(monkeypatch):
    row = {
        'status':'completed', 'answer':'已保存答案',
        'references_json':json.dumps([{'reference_id':'1','file_path':'policy.md','content':['原文']}]),
        'retrieval_json':json.dumps({'mode':'mix','policy_version':'test','strategy':'whole_query_rerank','degraded':False}),
        'llm_generated':1, 'http_status':200, 'error_stage':None, 'error_message':None,
    }
    monkeypatch.setattr(recorded_qa, 'get_qa_record', lambda engine, request_id, **kwargs: deepcopy(row), raising=False)
    return row


def replay():
    function = getattr(recorded_qa, 'load_existing_answer', None)
    assert callable(function), 'Add load_existing_answer() to app/recorded_qa.py'
    return function(object(), RECORD_ID)


def test_completed_record_restores_answer_references_and_retrieval(saved):
    answer = replay()
    assert answer.response == saved['answer']
    assert answer.references[0].file_path == 'policy.md'
    assert answer.references[0].content == ['原文']
    assert answer.retrieval.mode == 'mix'
    assert answer.llm_generated is True
    assert answer.response_time is None  # Original model response_time was not persisted.


def test_processing_returns_conflict_without_claiming_it_is_still_running(saved):
    saved['status'] = 'processing'
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        replay()
    assert caught.value.status_code == 409
    assert caught.value.request_id == RECORD_ID
    assert caught.value.stage == '请求状态'


def test_failed_record_returns_original_failure(saved):
    saved.update(status='failed', http_status=504, error_stage='回答模型', error_message='原请求超时')
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        replay()
    assert caught.value.status_code == 504
    assert caught.value.stage == '回答模型'
    assert caught.value.detail == '原请求超时'
    assert caught.value.request_id == RECORD_ID


def test_missing_record_does_not_start_new_work(saved, monkeypatch):
    monkeypatch.setattr(recorded_qa, 'get_qa_record', lambda *args, **kwargs: None)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        replay()
    assert caught.value.status_code == 404
    assert caught.value.request_id == RECORD_ID


def test_database_failure_is_sanitized_and_keeps_record_id(saved, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-password')
    monkeypatch.setattr(recorded_qa, 'get_qa_record', fail)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        replay()
    assert caught.value.status_code == 503
    assert caught.value.stage == '记录读取'
    assert caught.value.request_id == RECORD_ID
    assert 'private-password' not in caught.value.detail


@pytest.mark.parametrize('changes', [
    {'references_json':'not-json'}, {'answer':None}, {'status':'unknown'},
])
def test_corrupt_record_does_not_become_a_successful_answer(saved, changes):
    saved.update(changes)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        replay()
    assert caught.value.status_code == 500
    assert caught.value.stage == '记录读取'
    assert caught.value.request_id == RECORD_ID
