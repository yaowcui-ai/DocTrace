import json

import httpx2 as httpx
import pytest

from app.config import Settings
from app.retrieval_client import collect_retrieval


SETTINGS = Settings("http://rag.test", "test-secret")
CHUNK = {"chunk_id": "A", "reference_id": "5", "file_path": "a.md", "content": "Rule A"}


def test_sends_retrieval_only_request_and_preserves_chunks():
    body = {"status": "success", "data": {"chunks": [CHUNK]}}

    def handler(request):
        assert str(request.url) == "http://rag.test/query/data"
        assert request.headers["X-API-Key"] == "test-secret"
        assert json.loads(request.content) == {"query": "Question", "mode": "naive", "enable_rerank": False}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_retrieval(client, SETTINGS, "Question")
    assert result["error_kind"] is None
    assert result["chunks"] == [CHUNK]
    assert result["raw_response"] == body


@pytest.mark.parametrize("kind, expected", [
    ("timeout", "timeout"), ("http", "http_error"), ("failure", "upstream_error"),
    ("shape", "invalid_response"), ("duplicate", "invalid_response"),
])
def test_failures_are_not_successful_empty_retrieval(kind, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret", request=request)
        if kind == "http":
            return httpx.Response(503)
        if kind == "failure":
            return httpx.Response(200, json={"status": "failure", "data": {}})
        chunks = [CHUNK, CHUNK] if kind == "duplicate" else [{"content": 123}]
        return httpx.Response(200, json={"status": "success", "data": {"chunks": chunks}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = collect_retrieval(client, SETTINGS, "Question")
    assert record["error_kind"] == expected
    assert record["chunks"] is None
    assert len(calls) == 1
    assert "test-secret" not in json.dumps(record)
