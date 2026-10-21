"""Offline claim/reuse checks, including two concurrent database writers."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.qa_records import create_processing_record

KEY = 'e987d773-9207-4bc1-8f65-c6fd254c1e10'


def module():
    assert (Path(__file__).parents[1] / 'app/idempotency.py').exists(), 'Create app/idempotency.py first'
    return import_module('app.idempotency')


def claim(engine, **kwargs):
    values = dict(question='原问题', corpus_id='test', idempotency_key=KEY)
    values.update(kwargs)
    return module().claim_qa_record(engine, **values)


def count(engine):
    with engine.connect() as conn:
        return conn.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one()


def test_new_key_creates_one_processing_record(record_engine):
    record_id, created = claim(record_engine)
    assert created is True
    assert count(record_engine) == 1
    with record_engine.connect() as conn:
        row = conn.execute(text('SELECT * FROM qa_records')).mappings().one()
    assert row['request_id'] == record_id
    assert row['status'] == 'processing'


@pytest.mark.parametrize('status', ['processing', 'completed', 'failed'])
def test_existing_key_reuses_identity_without_resetting_state(record_engine, status):
    first = create_processing_record(record_engine, question='原问题', corpus_id='test', idempotency_key=KEY)
    with record_engine.begin() as conn:
        conn.execute(text('UPDATE qa_records SET status=:status WHERE request_id=:id'), {'status': status, 'id': first})
    assert claim(record_engine) == (first, False)
    assert count(record_engine) == 1
    with record_engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM qa_records')).scalar_one() == status


@pytest.mark.parametrize('changes', [{'question':'另一个问题'}, {'corpus_id':'another-corpus'}])
def test_reusing_key_with_different_inputs_is_a_conflict(record_engine, changes):
    m = module()
    first, _ = claim(record_engine)
    with pytest.raises(m.IdempotencyConflict) as caught:
        claim(record_engine, **changes)
    assert caught.value.request_id == first
    assert count(record_engine) == 1


def test_unrelated_integrity_error_is_not_treated_as_a_duplicate(record_engine, monkeypatch):
    m = module()
    original = IntegrityError('test SQL', {}, Exception('unrelated constraint'))
    def fail(*args, **kwargs):
        raise original
    monkeypatch.setattr(m, 'create_processing_record', fail)
    with pytest.raises(IntegrityError) as caught:
        claim(record_engine)
    assert caught.value is original


def test_database_unavailable_does_not_become_a_successful_reuse(record_engine, monkeypatch):
    m = module()
    def fail(*args, **kwargs):
        raise OperationalError('test SQL', {}, Exception('unavailable'))
    def forbidden(*args, **kwargs):
        pytest.fail('Connection failure is not a duplicate-key conflict')
    monkeypatch.setattr(m, 'create_processing_record', fail)
    monkeypatch.setattr(m, 'get_qa_record_by_key', forbidden)
    with pytest.raises(OperationalError):
        claim(record_engine)


def test_two_concurrent_requests_only_one_claims_new_work(record_engine):
    module()
    barrier = Barrier(2)
    def worker():
        barrier.wait(timeout=5)
        return claim(record_engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    assert count(record_engine) == 1
