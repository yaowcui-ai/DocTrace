import json

import httpx2 as httpx
import pytest

from app.rerank_client import collect_rerank
from app.rerank_config import RerankSettings


SETTINGS = RerankSettings("https://rerank.test/v1/rerank", "test-model", "test-secret")
CHUNKS = [
    {"chunk_id": "A", "file_path": "a.md", "reference_id": "1", "content": "alpha"},
    {"chunk_id": "B", "file_path": "b.md", "reference_id": "2", "content": "beta"},
]


def test_sends_all_candidates_and_preserves_provider_response():
    body = {"results": [{"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.2}], "meta": {"tokens": 12}}

    def handler(request):
        assert str(request.url) == SETTINGS.rerank_url
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert json.loads(request.content) == {
            "model": "test-model", "query": "question", "documents": ["alpha", "beta"],
            "top_n": 2, "return_documents": False}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = collect_rerank(client, SETTINGS, "question", CHUNKS)
    assert record["error_kind"] is None
    assert record["raw_response"] == body
    assert [x["chunk_id"] for x in record["ranked_chunks"]] == ["B", "A"]
    assert "test-secret" not in json.dumps(record)


@pytest.mark.parametrize("kind, expected", [
    ("timeout", "timeout"), ("connection", "transport_error"),
    ("http", "http_error"), ("json", "invalid_response"),
    ("nonfinite", "invalid_response"),
    ("duplicate", "invalid_response"), ("missing", "invalid_response"),
])
def test_failures_are_retained_without_retry(kind, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret", request=request)
        if kind == "connection":
            raise httpx.ConnectError("test-secret", request=request)
        if kind == "http":
            return httpx.Response(429)
        if kind == "json":
            return httpx.Response(200, text="invalid JSON")
        if kind == "nonfinite":
            return httpx.Response(200, text='{"results": [{"index": 0, "relevance_score": NaN}]}')
        results = [{"index": 0, "relevance_score": 0.8}]
        if kind == "duplicate":
            results *= 2
        return httpx.Response(200, json={"results": results})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = collect_rerank(client, SETTINGS, "question", CHUNKS)
    assert len(calls) == 1
    assert record["error_kind"] == expected
    assert record["ranked_chunks"] is None
    assert "test-secret" not in json.dumps(record)
    if kind in ("duplicate", "missing"):
        assert record["raw_response"] is not None
