"""Offline persistence checks; no real MySQL or model calls."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.qa_records import create_processing_record

KEY = '4af6be4a-51f1-4d9e-8c01-3149a5b79dc2'


def rows(engine):
    with engine.connect() as conn:
        return conn.execute(text('SELECT request_id, question, idempotency_key FROM qa_records')).mappings().all()


def test_key_is_saved_with_processing_record(record_engine):
    record_id = create_processing_record(record_engine, question='原问题', corpus_id='test', idempotency_key=KEY)
    row, = rows(record_engine)
    assert row['request_id'] == record_id
    assert row['idempotency_key'] == KEY


def test_duplicate_key_rejects_second_insert_and_preserves_first(record_engine):
    first = create_processing_record(record_engine, question='原问题', corpus_id='test', idempotency_key=KEY)
    with pytest.raises(IntegrityError):
        create_processing_record(record_engine, question='不同问题', corpus_id='test', idempotency_key=KEY)
    row, = rows(record_engine)
    assert row['request_id'] == first
    assert row['question'] == '原问题'


def test_new_keys_allow_intentional_repeat_questions(record_engine):
    for key in [KEY, 'd86a17e5-d95b-4e62-866e-1d4893db47ae']:
        create_processing_record(record_engine, question='相同问题', corpus_id='test', idempotency_key=key)
    assert len(rows(record_engine)) == 2


def test_legacy_calls_without_keys_still_create_separate_records(record_engine):
    for _ in range(2):
        create_processing_record(record_engine, question='旧调用', corpus_id='test')
    saved = rows(record_engine)
    assert len(saved) == 2
    assert all(row['idempotency_key'] is None for row in saved)


@pytest.mark.parametrize('status', ['processing', 'completed', 'failed'])
def test_lookup_by_key_returns_original_record_without_changing_it(record_engine, status):
    from app import qa_records
    record_id = create_processing_record(record_engine, question='原问题', corpus_id='test', idempotency_key=KEY)
    with record_engine.begin() as conn:
        conn.execute(text('UPDATE qa_records SET status=:status WHERE request_id=:id'), {'status':status, 'id':record_id})
    before = qa_records.get_qa_record(record_engine, record_id)
    found = qa_records.get_qa_record_by_key(record_engine, KEY)
    assert found == before
    assert found['request_id'] == record_id
    assert found['status'] == status
    assert qa_records.get_qa_record(record_engine, record_id) == before


@pytest.mark.parametrize('key', ['missing-key', "' OR 1=1 --"])
def test_missing_key_does_not_match_other_records(record_engine, key):
    from app import qa_records
    create_processing_record(record_engine, question='不可误读', corpus_id='test', idempotency_key=KEY)
    create_processing_record(record_engine, question='旧记录', corpus_id='test')
    assert qa_records.get_qa_record_by_key(record_engine, key) is None
