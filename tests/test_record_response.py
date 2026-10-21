"""Public history shape and explicit UTC serialization, without external I/O."""
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
from pydantic import ValidationError


def payload():
    return {
        "request_id": "79060ce7-f617-4db9-a3e3-804e7f3b012a",
        "question": "测试", "answer": None, "references": None, "retrieval": None,
        "corpus_id": "test", "status": "processing", "http_status": None,
        "error_stage": None, "error_message": None, "llm_generated": None,
        "duration_ms": None, "created_at": datetime(2026, 10, 16, 13, 37, 11),
        "updated_at": datetime(2026, 10, 16, 13, 37, 11),
    }


def test_pending_response_preserves_nulls_and_marks_utc():
    model = import_module("app.schemas").QARecordResponse
    result = model.model_validate(payload()).model_dump(mode="json")
    assert result["request_id"] == payload()["request_id"]
    assert result["references"] is None
    assert result["llm_generated"] is None
    assert result["created_at"] == "2026-10-16T13:37:11Z"


def test_native_mysql_boolean_and_json_shapes():
    model = import_module("app.schemas").QARecordResponse
    result = model.model_validate({**payload(), "status":"completed", "answer":"测试答案",
        "references":[], "llm_generated":1, "http_status":200, "duration_ms":123})
    assert result.llm_generated is True
    assert result.references == []


def test_aware_datetime_is_converted_to_utc():
    model = import_module("app.schemas").QARecordResponse
    result = model.model_validate({**payload(), "created_at":datetime(
        2026, 10, 16, 21, 37, 11, tzinfo=timezone(timedelta(hours=8)))})
    assert result.model_dump(mode="json")["created_at"] == "2026-10-16T13:37:11Z"


def test_invalid_status_is_rejected():
    model = import_module("app.schemas").QARecordResponse
    with pytest.raises(ValidationError):
        model.model_validate({**payload(), "status":"unrecognized"})
