"""Read-only history HTTP routes using temporary SQLite, no model calls."""
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.config import ConfigurationError
from app.lightrag_client import UpstreamError
from app.qa_records import create_processing_record, save_completed_record, save_failed_record
from app.schemas import MediumAskResponse


@pytest.fixture
def history_api(monkeypatch, record_engine):
    monkeypatch.setattr(main, "create_db_engine", lambda settings: record_engine)

    def forbidden(*args, **kwargs):
        pytest.fail("History reads must not call retrieval, generation, or create an HTTP client")
    monkeypatch.setattr(main, "run_medium_qa_pipeline", forbidden)
    monkeypatch.setattr(main, "make_qa_client", forbidden)

    def get(request_id):
        with TestClient(main.app) as client:
            return client.get("/records/" + request_id)
    return get


def seed(engine, *, status="processing"):
    request_id = create_processing_record(engine, owner_user_id="00000000-0000-4000-8000-000000000001", question="中文历史问题", corpus_id="test_corpus")
    if status == "completed":
        result = MediumAskResponse(response="已保存的中文答案", llm_generated=True,
            references=[{"reference_id":"1","file_path":"测试.md","content":["依据"]}],
            retrieval={"mode":"mix","policy_version":"test-only","strategy":"whole_query_rerank","degraded":False})
        save_completed_record(engine, request_id, result=result, duration_ms=1500)
    elif status == "failed":
        save_failed_record(engine, request_id,
            error=UpstreamError(504,"模拟生成超时",stage="回答模型"),duration_ms=1500)
    return request_id


def test_completed_history_decodes_json_and_boolean_and_utc(history_api, record_engine):
    request_id = seed(record_engine, status="completed")
    response = history_api(request_id)
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == request_id
    assert body["question"] == "中文历史问题"
    assert body["answer"] == "已保存的中文答案"
    assert body["status"] == "completed"
    assert body["http_status"] == 200
    assert body["llm_generated"] is True
    assert body["references"] == [{"reference_id":"1","file_path":"测试.md","content":["依据"]}]
    assert body["retrieval"]["mode"] == "mix"
    assert body["duration_ms"] == 1500
    assert body["created_at"].endswith("Z")
    assert "references_json" not in body


def test_processing_history_preserves_unknown_values(history_api, record_engine):
    response = history_api(seed(record_engine))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    for key in ("answer", "references", "retrieval", "http_status", "llm_generated", "duration_ms"):
        assert body[key] is None


def test_failed_history_is_a_successful_read_of_a_failed_request(history_api, record_engine):
    response = history_api(seed(record_engine, status="failed"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["http_status"] == 504
    assert body["error_stage"] == "回答模型"
    assert body["error_message"] == "模拟生成超时"
    assert body["llm_generated"] is None


def test_missing_identifier_returns_404(history_api):
    response = history_api(str(UUID(int=99)))
    assert response.status_code == 404
    assert response.json()["detail"] == "问答记录不存在。"


def test_invalid_identifier_is_rejected_before_database_query(history_api, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid UUID must be rejected before the database query")
    monkeypatch.setattr(main, "get_qa_record", forbidden, raising=False)
    assert history_api("not-a-uuid").status_code == 422


def test_missing_database_configuration_returns_503(history_api, monkeypatch):
    def missing():
        raise ConfigurationError("private-password")
    monkeypatch.setattr(main, "load_database_settings", missing)
    response = history_api(str(UUID(int=99)))
    assert response.status_code == 503
    assert "private-password" not in response.text


def test_database_error_returns_safe_503(history_api, monkeypatch):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password private-host")
    monkeypatch.setattr(main, "get_qa_record", unavailable, raising=False)
    response = history_api(str(UUID(int=99)))
    assert response.status_code == 503
    assert "private-password" not in response.text


@pytest.mark.parametrize("column", ["references_json", "retrieval_json"])
def test_corrupt_json_is_a_safe_error_not_a_missing_record(history_api, record_engine, column):
    request_id = seed(record_engine, status="completed")
    # column comes only from the fixed test parametrization, never request input.
    with record_engine.begin() as conn:
        conn.execute(text(f"UPDATE qa_records SET {column}=:bad WHERE request_id=:id"),
                     {"bad":"private-corrupt-data", "id":request_id})
    response = history_api(request_id)
    assert response.status_code == 500
    assert "private-corrupt-data" not in response.text


def test_repeated_history_reads_do_not_modify_records(history_api, record_engine):
    request_id = seed(record_engine, status="completed")
    with record_engine.connect() as conn:
        before = dict(conn.execute(text("SELECT * FROM qa_records")).mappings().one())
    assert history_api(request_id).status_code == 200
    assert history_api(request_id).status_code == 200
    with record_engine.connect() as conn:
        after = dict(conn.execute(text("SELECT * FROM qa_records")).mappings().one())
    assert after == before
