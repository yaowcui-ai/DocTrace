import pytest

from app.recorded_qa import run_recorded_qa, RecordedQAError
from app.qa_records import get_qa_record
from app.schemas import MediumAskResponse


KEY = '00000000-0000-4000-8000-000000000001'


@pytest.mark.parametrize('key', [None, KEY])
def test_mode_committed_before_answer_with_and_without_key(record_engine, key):
    def answer():
        from sqlalchemy import text
        with record_engine.connect() as connection:
            row = connection.execute(text('SELECT request_mode,status FROM qa_records')).one()
        assert tuple(row) == ('naive', 'processing')
        return MediumAskResponse(response='Synthetic', references=[], llm_generated=False)
    identifier, _ = run_recorded_qa(record_engine, question='Question', corpus_id='synthetic',
        answer_fn=answer, idempotency_key=key, request_mode='naive')
    assert get_qa_record(record_engine, identifier)['request_mode'] == 'naive'


def test_recorded_mode_change_conflicts_before_second_answer(record_engine):
    calls = []
    def answer():
        calls.append(1)
        return MediumAskResponse(response='Synthetic', references=[], llm_generated=False)
    identifier, _ = run_recorded_qa(record_engine, question='Question', corpus_id='synthetic',
        answer_fn=answer, idempotency_key=KEY, request_mode='naive')
    with pytest.raises(RecordedQAError) as error:
        run_recorded_qa(record_engine, question='Question', corpus_id='synthetic',
            answer_fn=answer, idempotency_key=KEY, request_mode='mix')
    assert error.value.status_code == 409 and error.value.request_id == identifier
    assert len(calls) == 1
