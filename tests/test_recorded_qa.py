"""Orchestration checks with fake I/O; no credentials or external calls."""
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.lightrag_client import UpstreamError
from app.qa_records import RecordStateError
from app.schemas import AskResponse


@pytest.fixture
def flow(monkeypatch):
    module = import_module("app.recorded_qa")
    calls = []
    request_id = str(uuid4())
    answer = AskResponse(response="测试答案", references=[], llm_generated=False)
    engine = object()

    def create(db, *, question, corpus_id, owner_user_id=None, request_mode='mix'):
        assert db is engine
        assert question == "测试问题"
        assert corpus_id == "test_corpus"
        calls.append("create")
        return request_id

    def complete(db, record_id, *, result, duration_ms):
        assert db is engine and record_id == request_id
        assert result is answer
        assert isinstance(duration_ms, int) and duration_ms >= 0
        calls.append("complete")

    errors = []

    def failed(db, record_id, *, error, duration_ms):
        assert db is engine and record_id == request_id
        assert isinstance(duration_ms, int) and duration_ms >= 0
        calls.append("failed")
        errors.append(error)

    def generate():
        calls.append("answer")
        return answer

    monkeypatch.setattr(module, "create_processing_record", create)
    monkeypatch.setattr(module, "save_completed_record", complete)
    monkeypatch.setattr(module, "save_failed_record", failed)

    def run(answer_fn=generate):
        return module.run_recorded_qa(engine, question="测试问题", corpus_id="test_corpus", answer_fn=answer_fn)

    return SimpleNamespace(module=module, calls=calls, request_id=request_id,
                           answer=answer, run=run, errors=errors)


def test_success_creates_before_answer_and_returns_record_id(flow):
    request_id, answer = flow.run()
    assert request_id == flow.request_id
    assert answer is flow.answer
    assert flow.calls == ["create", "answer", "complete"]


def test_insert_failure_prevents_generation_and_hides_database_details(flow, monkeypatch):
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("private-password private-host")

    monkeypatch.setattr(flow.module, "create_processing_record", unavailable)
    with pytest.raises(flow.module.RecordedQAError) as caught:
        flow.run()
    error = caught.value
    assert error.status_code == 503
    assert error.stage == "记录保存"
    assert error.request_id is None
    assert "private-password" not in str(error)
    assert flow.calls == []


def test_upstream_failure_is_saved_and_keeps_original_stage(flow):
    original = UpstreamError(504, "等待回答服务超时。", stage="回答模型")

    def generate():
        flow.calls.append("answer")
        raise original

    with pytest.raises(flow.module.RecordedQAError) as caught:
        flow.run(generate)
    assert flow.calls == ["create", "answer", "failed"]
    assert flow.errors == [original]
    assert caught.value.status_code == 504
    assert caught.value.stage == "回答模型"
    assert caught.value.detail == original.detail
    assert caught.value.request_id == flow.request_id


@pytest.mark.parametrize("database_error", [SQLAlchemyError("secret"), RecordStateError("conflict")])
def test_completed_save_failure_does_not_generate_again_or_mark_model_failed(flow, monkeypatch, database_error):
    def unavailable(*args, **kwargs):
        flow.calls.append("complete")
        raise database_error

    monkeypatch.setattr(flow.module, "save_completed_record", unavailable)
    with pytest.raises(flow.module.RecordedQAError) as caught:
        flow.run()
    assert flow.calls == ["create", "answer", "complete"]
    assert caught.value.status_code == 503
    assert caught.value.stage == "记录保存"
    assert caught.value.request_id == flow.request_id
    assert "secret" not in str(caught.value)


def test_error_save_failure_reports_persistence_stage_without_retry(flow, monkeypatch):
    def generate():
        flow.calls.append("answer")
        raise UpstreamError(504, "超时", stage="检索")

    def unavailable(*args, **kwargs):
        flow.calls.append("failed")
        raise SQLAlchemyError("secret")

    monkeypatch.setattr(flow.module, "save_failed_record", unavailable)
    with pytest.raises(flow.module.RecordedQAError) as caught:
        flow.run(generate)
    assert flow.calls == ["create", "answer", "failed"]
    assert caught.value.status_code == 503
    assert caught.value.stage == "记录保存"
    assert caught.value.request_id == flow.request_id


def test_unexpected_pipeline_exception_is_saved_without_raw_secrets(flow):
    def generate():
        flow.calls.append("answer")
        raise RuntimeError("private-token")

    with pytest.raises(flow.module.RecordedQAError) as caught:
        flow.run(generate)
    assert flow.calls == ["create", "answer", "failed"]
    assert caught.value.status_code == 500
    assert caught.value.stage == "内部处理"
    assert caught.value.request_id == flow.request_id
    assert "private-token" not in caught.value.detail
    assert "private-token" not in flow.errors[0].detail
