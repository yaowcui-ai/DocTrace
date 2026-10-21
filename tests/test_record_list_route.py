"""Summary list API: temporary SQLite, no MySQL credentials or model calls."""
from datetime import datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.config import ConfigurationError


@pytest.fixture
def list_api(monkeypatch, record_engine):
    monkeypatch.setattr(main, "create_db_engine", lambda settings: record_engine)

    def forbidden(*args, **kwargs):
        pytest.fail("Listing history must not call retrieval or models")
    monkeypatch.setattr(main, "make_qa_client", forbidden)
    monkeypatch.setattr(main, "run_medium_qa_pipeline", forbidden)

    def get(query=""):
        with TestClient(main.app) as client:
            return client.get("/records" + query)
    return get


def seed(engine):
    with engine.begin() as conn:
        for number in range(1,6):
            created = datetime(2026,10,16,12,0) + timedelta(seconds=number)
            conn.execute(text("""
                INSERT INTO qa_records (request_id,question,corpus_id,status,created_at,updated_at,answer,owner_user_id)
                VALUES (:id,:question,'test','completed',:created,:created,:answer,'00000000-0000-4000-8000-000000000001')
            """), {"id":str(UUID(int=number)), "question":f"问题{number}",
                    "created":created, "answer":"large answer " * 5000})


def test_default_page_is_summary_only_and_does_not_update_rows(list_api, record_engine):
    seed(record_engine)
    with record_engine.connect() as conn:
        before = [dict(row) for row in conn.execute(text("SELECT * FROM qa_records")).mappings()]
    response = list_api()
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 20 and body["offset"] == 0
    assert len(body["items"]) == 5
    assert body["has_more"] is False and body["next_offset"] is None
    assert body["items"][0]["request_id"] == str(UUID(int=5))
    assert body["items"][0]["created_at"].endswith("Z")
    assert all(set(item) == {"request_id","question","corpus_id","status","http_status",
                             "duration_ms","created_at","updated_at"} for item in body["items"])
    with record_engine.connect() as conn:
        after = [dict(row) for row in conn.execute(text("SELECT * FROM qa_records")).mappings()]
    assert before == after


def test_explicit_pagination_reaches_correct_page(list_api, record_engine):
    seed(record_engine)
    response = list_api("?limit=2&offset=2")
    assert response.status_code == 200
    body = response.json()
    assert [row["request_id"] for row in body["items"]] == [str(UUID(int=n)) for n in (3,2)]
    assert body["has_more"] is True and body["next_offset"] == 4


def test_last_page_has_no_next_offset(list_api, record_engine):
    seed(record_engine)
    response = list_api("?limit=2&offset=4")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False and body["next_offset"] is None


def test_empty_list_is_200_not_404(list_api):
    response = list_api()
    assert response.status_code == 200
    assert response.json() == {"items":[],"limit":20,"offset":0,"has_more":False,"next_offset":None}


@pytest.mark.parametrize("query", ["?limit=0","?limit=101","?limit=abc","?limit=true","?offset=-1","?offset=abc"])
def test_invalid_query_is_rejected_before_sql(list_api, monkeypatch, query):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid parameters must not enter the query function")
    monkeypatch.setattr(main,"list_qa_records",forbidden,raising=False)
    assert list_api(query).status_code == 422


def test_missing_database_configuration_returns_safe_503(list_api, monkeypatch):
    def missing():
        raise ConfigurationError("private-password")
    monkeypatch.setattr(main,"load_database_settings",missing)
    response = list_api()
    assert response.status_code == 503
    assert "private-password" not in response.text


def test_database_query_failure_returns_safe_503(list_api, monkeypatch):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password")
    monkeypatch.setattr(main,"list_qa_records",unavailable,raising=False)
    response = list_api()
    assert response.status_code == 503
    assert "private-password" not in response.text


def test_invalid_saved_summary_is_safe_500(list_api, record_engine):
    seed(record_engine)
    with record_engine.begin() as conn:
        conn.execute(text("UPDATE qa_records SET status='private-invalid-status'"))
    response = list_api()
    assert response.status_code == 500
    assert "private-invalid-status" not in response.text
