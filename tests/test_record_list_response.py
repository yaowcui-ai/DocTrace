from datetime import datetime
from importlib import import_module

import pytest
from pydantic import ValidationError


def page():
    return {
        "items":[{"request_id":"79060ce7-f617-4db9-a3e3-804e7f3b012a", "question":"问题",
                  "corpus_id":"test", "status":"processing", "http_status":None,
                  "duration_ms":None, "created_at":datetime(2026,10,16,13,0),
                  "updated_at":datetime(2026,10,16,13,0)}],
        "limit":20, "offset":0, "has_more":False, "next_offset":None,
    }


def test_summary_page_preserves_nulls_and_utc():
    model = import_module("app.schemas").QARecordListResponse
    result = model.model_validate(page()).model_dump(mode="json")
    assert result["items"][0]["created_at"] == "2026-10-16T13:00:00Z"
    assert result["items"][0]["http_status"] is None
    assert result["next_offset"] is None
    assert "answer" not in result["items"][0]


def test_invalid_summary_status_is_rejected():
    model = import_module("app.schemas").QARecordListResponse
    payload = page()
    payload["items"][0]["status"] = "bad"
    with pytest.raises(ValidationError):
        model.model_validate(payload)
