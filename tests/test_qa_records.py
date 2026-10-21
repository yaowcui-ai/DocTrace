"""Offline SQL/transaction checks; MySQL compatibility is verified separately."""
from datetime import datetime, timezone
from importlib import import_module
import json
from uuid import UUID

import pytest
from sqlalchemy import event, text


def test_insert_is_committed_and_question_is_bound_as_data(record_engine):
    create = import_module("app.qa_records").create_processing_record
    question = "员工's 假期？'); DROP TABLE qa_records; --"
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    request_id = create(record_engine, question=question, corpus_id="gitlab_hr_v3")
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert str(UUID(request_id)) == request_id
    with record_engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM qa_records")).mappings().one()
    assert row["request_id"] == request_id
    assert row["question"] == question
    assert row["corpus_id"] == "gitlab_hr_v3"
    assert row["status"] == "processing"
    assert row["answer"] is None
    created = datetime.fromisoformat(row["created_at"])
    assert before <= created <= after
    assert row["created_at"] == row["updated_at"]


def test_same_question_creates_two_independent_records(record_engine):
    create = import_module("app.qa_records").create_processing_record
    first = create(record_engine, question="相同问题", corpus_id="gitlab_hr_v3")
    second = create(record_engine, question="相同问题", corpus_id="gitlab_hr_v3")
    assert first != second
    with record_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM qa_records")).scalar_one() == 2


def test_exception_after_insert_rolls_back_and_propagates(record_engine):
    create = import_module("app.qa_records").create_processing_record

    def fail_after_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT"):
            raise RuntimeError("simulated failure before commit")

    event.listen(record_engine, "after_cursor_execute", fail_after_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            create(record_engine, question="测试回滚", corpus_id="gitlab_hr_v3")
    finally:
        event.remove(record_engine, "after_cursor_execute", fail_after_insert)
    with record_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM qa_records")).scalar_one() == 0


def sample_answer(*, medium=True):
    from app.schemas import AskResponse, MediumAskResponse
    values = {
        "response": "仅用于数据库测试的答案。",
        "references": [{"reference_id": "1", "file_path": "测试.md", "content": ["测试依据"]}],
        "llm_generated": False,
    }
    if medium:
        return MediumAskResponse(**values, retrieval={
            "mode": "mix", "policy_version": "test-only",
            "strategy": "whole_query_rerank", "degraded": False,
        })
    return AskResponse(**values)


def read_record(engine, request_id):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM qa_records WHERE request_id=:id"),
                            {"id": request_id}).mappings().one()


def test_complete_saves_answer_json_and_preserves_identity(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="原问题", corpus_id="gitlab_hr_v3")
    before = read_record(record_engine, request_id)
    result = sample_answer()
    module.save_completed_record(record_engine, request_id, result=result, duration_ms=1234)
    row = read_record(record_engine, request_id)
    assert row["status"] == "completed"
    assert row["answer"] == result.response
    assert json.loads(row["references_json"]) == result.model_dump(mode="json")["references"]
    assert json.loads(row["retrieval_json"]) == result.retrieval.model_dump(mode="json")
    assert row["http_status"] == 200
    assert row["llm_generated"] == 0
    assert row["duration_ms"] == 1234
    for field in ("request_id", "question", "corpus_id", "created_at"):
        assert row[field] == before[field]
    assert row["updated_at"] >= before["updated_at"]


def test_legacy_response_has_sql_null_retrieval(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    module.save_completed_record(record_engine, request_id, result=sample_answer(medium=False), duration_ms=0)
    assert read_record(record_engine, request_id)["retrieval_json"] is None


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_record_cannot_be_overwritten(record_engine, status):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    with record_engine.begin() as conn:
        conn.execute(text("UPDATE qa_records SET status=:status, answer='original' WHERE request_id=:id"),
                     {"status": status, "id": request_id})
    before = dict(read_record(record_engine, request_id))
    with pytest.raises(module.RecordStateError):
        module.save_completed_record(record_engine, request_id, result=sample_answer(), duration_ms=1)
    assert dict(read_record(record_engine, request_id)) == before


def test_missing_record_raises_instead_of_reporting_success(record_engine):
    module = import_module("app.qa_records")
    with pytest.raises(module.RecordStateError):
        module.save_completed_record(record_engine, str(UUID(int=1)), result=sample_answer(), duration_ms=1)


def test_update_exception_preserves_committed_processing_record(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            raise RuntimeError("simulated update failure")

    event.listen(record_engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated update failure"):
            module.save_completed_record(record_engine, request_id, result=sample_answer(), duration_ms=1)
    finally:
        event.remove(record_engine, "after_cursor_execute", fail)
    row = read_record(record_engine, request_id)
    assert row["status"] == "processing"
    assert row["answer"] is None


def test_negative_duration_is_rejected_before_update(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    with pytest.raises(ValueError):
        module.save_completed_record(record_engine, request_id, result=sample_answer(), duration_ms=-1)
    assert read_record(record_engine, request_id)["status"] == "processing"


def sample_failure():
    from app.lightrag_client import UpstreamError
    return UpstreamError(504, "模拟：等待生成服务超时。", stage="生成")


def test_failure_saves_error_without_claiming_model_did_not_run(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试失败", corpus_id="test")
    before = read_record(record_engine, request_id)
    module.save_failed_record(record_engine, request_id, error=sample_failure(), duration_ms=5000)
    row = read_record(record_engine, request_id)
    assert row["status"] == "failed"
    assert row["http_status"] == 504
    assert row["error_stage"] == "生成"
    assert row["error_message"] == "模拟：等待生成服务超时。"
    assert row["duration_ms"] == 5000
    for field in ("answer", "references_json", "retrieval_json", "llm_generated"):
        assert row[field] is None
    for field in ("request_id", "question", "corpus_id", "created_at"):
        assert row[field] == before[field]


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_failure_cannot_overwrite_terminal_record(record_engine, status):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    with record_engine.begin() as conn:
        conn.execute(text("UPDATE qa_records SET status=:status WHERE request_id=:id"),
                     {"status": status, "id": request_id})
    before = dict(read_record(record_engine, request_id))
    with pytest.raises(module.RecordStateError):
        module.save_failed_record(record_engine, request_id, error=sample_failure(), duration_ms=1)
    assert dict(read_record(record_engine, request_id)) == before


def test_failure_rejects_missing_record(record_engine):
    module = import_module("app.qa_records")
    with pytest.raises(module.RecordStateError):
        module.save_failed_record(record_engine, str(UUID(int=2)), error=sample_failure(), duration_ms=1)


def test_failure_update_rollback_preserves_processing(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE"):
            raise RuntimeError("simulated failure persistence error")

    event.listen(record_engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated failure persistence error"):
            module.save_failed_record(record_engine, request_id, error=sample_failure(), duration_ms=1)
    finally:
        event.remove(record_engine, "after_cursor_execute", fail)
    row = read_record(record_engine, request_id)
    assert row["status"] == "processing"
    assert row["error_message"] is None


def test_failure_rejects_negative_duration(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    with pytest.raises(ValueError):
        module.save_failed_record(record_engine, request_id, error=sample_failure(), duration_ms=-1)
    assert read_record(record_engine, request_id)["status"] == "processing"


def test_failure_rejects_success_http_status(record_engine):
    from app.lightrag_client import UpstreamError
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="测试", corpus_id="test")
    with pytest.raises(ValueError):
        module.save_failed_record(record_engine, request_id,
                                  error=UpstreamError(200, "not an error"), duration_ms=1)
    assert read_record(record_engine, request_id)["status"] == "processing"


def test_get_processing_record_returns_fields_without_modifying_row(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="查询处理中记录", corpus_id="test")
    before = dict(read_record(record_engine, request_id))
    result = module.get_qa_record(record_engine, request_id)
    # Internal retry keys are not part of the history detail projection.
    assert result == {key: value for key, value in before.items() if key not in {"idempotency_key", "owner_user_id"}}
    assert result["status"] == "processing"
    assert result["answer"] is None
    assert result["llm_generated"] is None
    assert dict(read_record(record_engine, request_id)) == before


def test_get_completed_record_preserves_answer_and_json_columns(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="查询成功记录", corpus_id="test")
    answer = sample_answer()
    module.save_completed_record(record_engine, request_id, result=answer, duration_ms=10)
    result = module.get_qa_record(record_engine, request_id)
    assert result["request_id"] == request_id
    assert result["status"] == "completed"
    assert result["answer"] == answer.response
    assert json.loads(result["references_json"]) == answer.model_dump(mode="json")["references"]
    assert json.loads(result["retrieval_json"]) == answer.retrieval.model_dump(mode="json")


def test_get_failed_record_preserves_error_and_unknown_generation(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="查询失败记录", corpus_id="test")
    module.save_failed_record(record_engine, request_id, error=sample_failure(), duration_ms=10)
    result = module.get_qa_record(record_engine, request_id)
    assert result["status"] == "failed"
    assert result["http_status"] == 504
    assert result["error_stage"] == "生成"
    assert result["error_message"] == sample_failure().detail
    assert result["llm_generated"] is None


def test_get_missing_record_returns_none(record_engine):
    module = import_module("app.qa_records")
    assert module.get_qa_record(record_engine, str(UUID(int=3))) is None


def test_get_identifier_is_bound_as_data_and_does_not_expose_other_records(record_engine):
    module = import_module("app.qa_records")
    request_id = module.create_processing_record(record_engine, question="不得误读", corpus_id="test")
    assert module.get_qa_record(record_engine, "' OR 1=1 --") is None
    assert module.get_qa_record(record_engine, request_id)["question"] == "不得误读"
