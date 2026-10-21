"""Real offline persistence with fake answer generation; no paid requests."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import recorded_qa
from app.lightrag_client import UpstreamError
from app.qa_records import create_processing_record, get_qa_record
from app.schemas import MediumAskResponse

KEY = 'a61fabef-8ae8-4231-91ac-4496b613765a'


def invoke(engine, answer_fn, **changes):
    args = dict(question='测试问题', corpus_id='test', idempotency_key=KEY, answer_fn=answer_fn)
    args.update(changes)
    return recorded_qa.run_recorded_qa(engine, **args)


def forbidden():
    pytest.fail('Reused operations must not call the answer service')


def answer():
    return MediumAskResponse(response='离线测试答案', references=[], llm_generated=False,
        retrieval={'mode':'mix','policy_version':'test','strategy':'whole_query_rerank','degraded':False})


def test_completed_operation_replays_without_calling_answer_again(record_engine):
    first_id, first = invoke(record_engine, answer)
    before = get_qa_record(record_engine, first_id)
    second_id, second = invoke(record_engine, forbidden)
    assert first_id == second_id
    assert first.model_dump() == second.model_dump()
    assert get_qa_record(record_engine, first_id) == before


def test_processing_operation_does_not_generate_or_mark_failed(record_engine):
    original = create_processing_record(record_engine, question='测试问题', corpus_id='test', idempotency_key=KEY)
    before = get_qa_record(record_engine, original)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        invoke(record_engine, forbidden)
    assert caught.value.status_code == 409
    assert caught.value.request_id == original
    assert get_qa_record(record_engine, original) == before


def test_failed_operation_replays_error_without_overwriting_original(record_engine):
    def timeout():
        raise UpstreamError(504, '原回答超时', stage='回答模型')
    with pytest.raises(recorded_qa.RecordedQAError) as first:
        invoke(record_engine, timeout)
    original = first.value.request_id
    before = get_qa_record(record_engine, original)
    with pytest.raises(recorded_qa.RecordedQAError) as second:
        invoke(record_engine, forbidden)
    assert second.value.request_id == original
    assert second.value.status_code == 504
    assert second.value.detail == first.value.detail
    assert second.value.stage == '回答模型'
    assert get_qa_record(record_engine, original) == before


@pytest.mark.parametrize('changes', [{'question':'另一个问题'}, {'corpus_id':'another-corpus'}])
def test_key_input_conflict_is_409_and_preserves_original(record_engine, changes):
    original, _ = invoke(record_engine, answer)
    before = get_qa_record(record_engine, original)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        invoke(record_engine, forbidden, **changes)
    assert caught.value.status_code == 409
    assert caught.value.stage == '请求校验'
    assert caught.value.request_id == original
    assert get_qa_record(record_engine, original) == before


def test_new_key_allows_intentional_new_answer(record_engine):
    first, _ = invoke(record_engine, answer)
    second, _ = invoke(record_engine, answer, idempotency_key='4326c6f4-09b3-46cc-ad13-a4f92c436a8e')
    assert first != second
    with record_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one() == 2


def test_claim_database_error_stops_before_answer_and_hides_secrets(record_engine, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError('private-password')
    monkeypatch.setattr(recorded_qa, 'claim_qa_record', fail, raising=False)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        invoke(record_engine, forbidden)
    assert caught.value.status_code == 503
    assert caught.value.stage == '记录保存'
    assert caught.value.request_id is None
    assert 'private-password' not in caught.value.detail


def test_replay_read_failure_does_not_mark_existing_record_failed(record_engine, monkeypatch):
    original, _ = invoke(record_engine, answer)
    before = get_qa_record(record_engine, original)
    def fail(*args, **kwargs):
        raise recorded_qa.RecordedQAError(UpstreamError(503, '读取失败', stage='记录读取'), original)
    monkeypatch.setattr(recorded_qa, 'load_existing_answer', fail)
    with pytest.raises(recorded_qa.RecordedQAError) as caught:
        invoke(record_engine, forbidden)
    assert caught.value.stage == '记录读取'
    assert get_qa_record(record_engine, original) == before
