import pytest

from app.idempotency import claim_qa_record, IdempotencyConflict
from app.qa_records import create_processing_record, get_qa_record, get_qa_record_by_key


KEY = '00000000-0000-4000-8000-000000000001'


def test_selected_mode_saved_before_external_request(record_engine):
    identifier = create_processing_record(record_engine, question='Question', corpus_id='synthetic',
        idempotency_key=KEY, request_mode='naive')
    row = get_qa_record(record_engine, identifier)
    assert row['status'] == 'processing' and row['request_mode'] == 'naive'
    assert get_qa_record_by_key(record_engine, KEY)['request_mode'] == 'naive'


def test_same_question_and_mode_reuses_record(record_engine):
    first, created = claim_qa_record(record_engine, question='Question', corpus_id='synthetic',
        idempotency_key=KEY, request_mode='naive')
    second, created_again = claim_qa_record(record_engine, question='Question', corpus_id='synthetic',
        idempotency_key=KEY, request_mode='naive')
    assert created and not created_again and first == second


def test_same_key_different_mode_conflicts(record_engine):
    identifier, _ = claim_qa_record(record_engine, question='Question', corpus_id='synthetic',
        idempotency_key=KEY, request_mode='naive')
    with pytest.raises(IdempotencyConflict) as error:
        claim_qa_record(record_engine, question='Question', corpus_id='synthetic',
            idempotency_key=KEY, request_mode='mix')
    assert error.value.request_id == identifier


def test_legacy_call_keeps_mix_default(record_engine):
    identifier = create_processing_record(record_engine, question='Question', corpus_id='synthetic')
    assert get_qa_record(record_engine, identifier)['request_mode'] == 'mix'


def test_invalid_mode_rejected_before_insert(record_engine):
    with pytest.raises(ValueError):
        create_processing_record(record_engine, question='Question', corpus_id='synthetic', request_mode='auto')
