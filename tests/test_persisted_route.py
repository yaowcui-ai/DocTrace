"""API plus real repository transactions against temporary SQLite, fake model I/O."""
from contextlib import nullcontext
import json
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import main, recorded_qa
from app.answer_config import AnswerSettings
from app.config import ConfigurationError, Settings
from app.lightrag_client import UpstreamError
from app.medium_config import MediumSettings
from app.schemas import AskResponse, MediumAskResponse


def rows(engine):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text("SELECT * FROM qa_records")).mappings()]


@pytest.fixture
def api(monkeypatch, record_engine):
    calls = []
    answer = MediumAskResponse(response="测试政策答案。", references=[], llm_generated=True,
        retrieval={"mode":"mix","policy_version":"test-only", "strategy":"whole_query_rerank","degraded":False})
    monkeypatch.setattr(main, "create_db_engine", lambda settings: record_engine)
    monkeypatch.setattr(main, "load_medium_settings", lambda: MediumSettings(Settings("http://rag.test", "dummy"), 40000, "test_corpus"))
    monkeypatch.setattr(main, "load_answer_settings", lambda: AnswerSettings("https://answer.test/chat/completions", "dummy", "dummy"))
    monkeypatch.setattr(main, "make_qa_client", lambda: nullcontext(object()))

    def generate(question, client, rag, settings, *, max_total_tokens, mode):
        assert question == "测试问题"
        assert max_total_tokens == 40000
        calls.append("answer")
        # A separate connection can already see the committed processing row.
        saved = rows(record_engine)
        assert len(saved) == 1 and saved[0]["status"] == "processing"
        return answer

    monkeypatch.setattr(main, "run_selected_qa_pipeline", generate)

    def post(question="  测试问题  "):
        with TestClient(main.app) as client:
            return client.post("/ask/optimized", json={"question":question, "mode":"mix"})

    return SimpleNamespace(engine=record_engine, calls=calls, answer=answer, post=post)


def test_success_returns_id_matching_committed_database_row(api):
    response = api.post()
    assert response.status_code == 200
    body = response.json()
    assert str(UUID(body["request_id"])) == body["request_id"]
    row, = rows(api.engine)
    assert row["request_id"] == body["request_id"]
    assert row["question"] == "测试问题"
    assert row["corpus_id"] == "test_corpus"
    assert row["status"] == "completed"
    assert row["answer"] == body["response"]
    assert json.loads(row["retrieval_json"]) == body["retrieval"]
    assert api.calls == ["answer"]


def test_upstream_error_returns_id_and_commits_failed_row(api, monkeypatch):
    def fail(*args, **kwargs):
        api.calls.append("answer")
        raise UpstreamError(504, "模拟生成超时。", stage="回答模型")
    monkeypatch.setattr(main, "run_selected_qa_pipeline", fail)
    response = api.post()
    assert response.status_code == 504
    detail = response.json()["detail"]
    row, = rows(api.engine)
    assert detail["request_id"] == row["request_id"]
    assert detail["stage"] == row["error_stage"] == "回答模型"
    assert row["status"] == "failed"
    assert row["http_status"] == 504
    assert row["llm_generated"] is None


def test_missing_database_configuration_does_not_call_pipeline(api, monkeypatch):
    def missing():
        raise ConfigurationError("private-password")
    monkeypatch.setattr(main, "load_database_settings", missing)
    response = api.post()
    assert response.status_code == 503
    assert response.json()["detail"]["stage"] == "记录保存"
    assert response.json()["detail"]["request_id"] is None
    assert "private-password" not in response.text
    assert api.calls == []
    assert rows(api.engine) == []


def test_insert_failure_prevents_model_call(api, monkeypatch):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password")
    monkeypatch.setattr(recorded_qa, "create_processing_record", unavailable)
    response = api.post()
    assert response.status_code == 503
    assert response.json()["detail"]["request_id"] is None
    assert response.json()["detail"]["stage"] == "记录保存"
    assert api.calls == []
    assert "private-password" not in response.text


def test_answer_save_failure_returns_persistence_error_and_retains_pending(api, monkeypatch):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password")
    monkeypatch.setattr(recorded_qa, "save_completed_record", unavailable)
    response = api.post()
    assert response.status_code == 503
    row, = rows(api.engine)
    assert response.json()["detail"]["request_id"] == row["request_id"]
    assert response.json()["detail"]["stage"] == "记录保存"
    assert row["status"] == "processing"
    assert row["answer"] is None
    assert api.calls == ["answer"]
    assert "private-password" not in response.text


def test_failed_save_failure_returns_persistence_error(api, monkeypatch):
    def fail(*args, **kwargs):
        api.calls.append("answer")
        raise UpstreamError(504, "超时", stage="检索")
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password")
    monkeypatch.setattr(main, "run_selected_qa_pipeline", fail)
    monkeypatch.setattr(recorded_qa, "save_failed_record", unavailable)
    response = api.post()
    assert response.status_code == 503
    row, = rows(api.engine)
    assert response.json()["detail"]["request_id"] == row["request_id"]
    assert response.json()["detail"]["stage"] == "记录保存"
    assert row["status"] == "processing"
    assert api.calls == ["answer"]


def test_invalid_question_does_not_insert_or_generate(api):
    assert api.post("   ").status_code == 422
    assert api.calls == []
    assert rows(api.engine) == []


def test_unexpected_error_is_sanitized_and_saved(api, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-token")
    monkeypatch.setattr(main, "run_selected_qa_pipeline", fail)
    response = api.post()
    assert response.status_code == 500
    row, = rows(api.engine)
    assert row["status"] == "failed"
    assert response.json()["detail"]["stage"] == "内部处理"
    assert response.json()["detail"]["request_id"] == row["request_id"]
    assert "private-token" not in response.text + row["error_message"]


def test_insufficient_evidence_is_completed_without_claiming_model_generation(api, monkeypatch):
    monkeypatch.setattr(main, "run_selected_qa_pipeline", lambda *args, **kwargs: AskResponse(
        response="证据不足。", references=[], llm_generated=False))
    response = api.post()
    assert response.status_code == 200
    row, = rows(api.engine)
    assert row["status"] == "completed"
    assert row["llm_generated"] == 0
    assert response.json()["retrieval"] is None
    assert response.json()["request_id"] == row["request_id"]
