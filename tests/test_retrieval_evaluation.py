"""Retrieval-only collection contract. All requests use MockTransport."""

import json
from datetime import datetime, timezone

import httpx2 as httpx
import pytest

from app import evaluate
from app.config import Settings


CASE = {"id": "HR-D06", "question": "How much notice for PTO?",
        "evidence": [{"file_path": "pto.md", "quote": "six business days"}]}
SETTINGS = Settings(lightrag_url="http://rag.test", lightrag_api_key="test-key")
PAYLOAD = {"status": "success", "message": "ok", "metadata": {}, "data": {
    "chunks": [{"reference_id": "1", "file_path": "pto.md", "chunk_id": "chunk-1",
                "content": "Give six business days notice."}], "references": []}}


def test_each_retrieval_record_has_its_own_timezone_aware_start():
    before = datetime.now(timezone.utc)
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=PAYLOAD))) as client:
        record = evaluate.evaluate_retrieval_case(client, SETTINGS, CASE)
    started = datetime.fromisoformat(record["started_at_utc"])
    assert started.tzinfo is not None
    assert before <= started <= datetime.now(timezone.utc)


def test_retrieval_endpoint_auth_mode_and_saved_evidence():
    def handler(request):
        assert str(request.url) == "http://rag.test/query/data"
        assert request.headers["X-API-Key"] == "test-key"
        assert json.loads(request.content) == {
            "query": CASE["question"], "mode": "naive", "enable_rerank": False}
        return httpx.Response(200, json=PAYLOAD)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = evaluate.evaluate_retrieval_case(client, SETTINGS, CASE)
    assert record["result"] == PAYLOAD
    assert record["error_kind"] is None
    assert record["evidence_coverage"]["coverage"] == 1.0
    assert record["retrieved_chunk_count"] == 1
    assert record["elapsed_seconds"] >= 0
    assert "test-key" not in json.dumps(record)


@pytest.mark.parametrize("scenario, expected", [
    ("http", "http_error"), ("failure", "upstream_error"),
    ("malformed", "invalid_response"), ("timeout", "timeout"),
])
def test_failure_is_preserved_without_retry_or_false_zero(scenario, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if scenario == "timeout":
            raise httpx.ReadTimeout("test-key", request=request)
        if scenario == "http":
            return httpx.Response(503)
        if scenario == "failure":
            return httpx.Response(200, json={"status": "failure", "data": {}})
        return httpx.Response(200, json={"status": "success", "data": {"chunks": "bad"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = evaluate.evaluate_retrieval_case(client, SETTINGS, CASE)
    assert len(calls) == 1
    assert record["error_kind"] == expected
    assert record["evidence_coverage"]["status"] == "not_evaluated"
    assert record["evidence_coverage"]["coverage"] is None


def test_successful_empty_retrieval_is_zero_coverage():
    def handler(request):
        return httpx.Response(200, json={"status": "success", "data": {"chunks": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = evaluate.evaluate_retrieval_case(client, SETTINGS, CASE)
    assert record["error_kind"] is None
    assert record["evidence_coverage"]["coverage"] == 0.0
