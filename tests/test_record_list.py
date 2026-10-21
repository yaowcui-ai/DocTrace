"""Summary-only offset pagination, against a temporary offline database."""
from datetime import datetime, timedelta
from importlib import import_module
from uuid import UUID

import pytest
from sqlalchemy import event, text


def seed(engine):
    base = datetime(2026, 10, 16, 12, 0)
    with engine.begin() as conn:
        for number in range(1, 7):
            # Pairs share a timestamp; UUID must break the tie consistently.
            created = base + timedelta(seconds=(number - 1) // 2)
            conn.execute(text("""
                INSERT INTO qa_records (
                    request_id, question, corpus_id, status, created_at, updated_at, answer
                ) VALUES (:id, :question, 'test', :status, :created, :created, :answer)
            """), {"id":str(UUID(int=number)), "question":f"问题{number}",
                    "status":("processing", "completed", "failed")[(number - 1) % 3],
                    "created":created, "answer":"large answer " * 5000})


def list_records(engine, **kwargs):
    return import_module("app.qa_records").list_qa_records(engine, **kwargs)


def test_empty_table_has_no_next_page(record_engine):
    assert list_records(record_engine) == {
        "items":[], "limit":20, "offset":0, "has_more":False, "next_offset":None,
    }


def test_page_order_is_newest_first_with_deterministic_ties(record_engine):
    seed(record_engine)
    first = list_records(record_engine, limit=2, offset=0)
    second = list_records(record_engine, limit=2, offset=2)
    assert [row["request_id"] for row in first["items"]] == [str(UUID(int=n)) for n in (6, 5)]
    assert [row["request_id"] for row in second["items"]] == [str(UUID(int=n)) for n in (4, 3)]
    assert first["has_more"] is True and first["next_offset"] == 2
    assert second["has_more"] is True and second["next_offset"] == 4
    assert second["offset"] == 2 and second["limit"] == 2


def test_full_last_page_does_not_claim_another_page(record_engine):
    seed(record_engine)
    page = list_records(record_engine, limit=2, offset=4)
    assert [row["request_id"] for row in page["items"]] == [str(UUID(int=n)) for n in (2, 1)]
    assert page["has_more"] is False
    assert page["next_offset"] is None


def test_offset_past_last_record_returns_empty_page(record_engine):
    seed(record_engine)
    page = list_records(record_engine, limit=2, offset=99)
    assert page["items"] == []
    assert page["has_more"] is False
    assert page["next_offset"] is None


def test_summary_query_does_not_load_answers_or_evidence(record_engine):
    seed(record_engine)
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement.lower())

    event.listen(record_engine, "before_cursor_execute", capture)
    try:
        page = list_records(record_engine, limit=2, offset=0)
    finally:
        event.remove(record_engine, "before_cursor_execute", capture)

    expected = {"request_id", "question", "corpus_id", "status", "http_status",
                "duration_ms", "created_at", "updated_at"}
    assert all(set(row) == expected for row in page["items"])
    assert len(queries) == 1
    assert not any(word in queries[0] for word in ("answer", "references_json", "retrieval_json", "count("))


@pytest.mark.parametrize("limit,offset", [(0,0), (101,0), (2,-1), (True,0), (2,1.5)])
def test_invalid_pagination_is_rejected_before_query(record_engine, limit, offset):
    with pytest.raises(ValueError):
        list_records(record_engine, limit=limit, offset=offset)
