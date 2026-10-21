import json

import httpx2 as httpx
import pytest

from app import qa_pipeline
from app.answer_config import AnswerSettings
from app.config import Settings
from app.lightrag_client import UpstreamError
from app.rerank_config import RerankSettings


RAG = Settings("http://rag.test", "service-key")
RERANK = RerankSettings("https://rerank.test/v1/rerank", "rerank-model", "provider-key")
ANSWER = AnswerSettings("https://answer.test/chat/completions", "answer-model", "answer-key")
CHUNKS = [
    {"chunk_id": "A", "reference_id": "9", "file_path": "a.md", "content": "Rule A"},
    {"chunk_id": "B", "reference_id": "3", "file_path": "b.md", "content": "Unrelated B"},
]


def run(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return qa_pipeline.run_qa_pipeline(
            "Question", client, RAG, RERANK, ANSWER, max_chars=100, min_score=0.3)


def test_generation_receives_selected_evidence_and_matching_new_references():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "rag.test":
            return httpx.Response(200, json={"status": "success", "data": {"chunks": CHUNKS}})
        if request.url.host == "rerank.test":
            return httpx.Response(200, json={"results": [
                {"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]})
        payload = json.loads(request.content)
        evidence = json.loads(payload["messages"][1]["content"])["evidence"]
        assert [x["chunk_id"] for x in evidence] == ["A"]
        assert evidence[0]["reference_id"] == "1"
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "Rule A [1]"}, "finish_reason": "stop"}]})

    result = run(handler)
    assert len(calls) == 3
    assert result.llm_generated is True
    assert result.references[0].reference_id == "1"
    assert result.references[0].file_path == "a.md"
    assert result.response_time >= 0


def test_empty_retrieval_short_circuits_before_rerank_or_answer():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "success", "data": {"chunks": []}})

    result = run(handler)
    assert len(calls) == 1
    assert result.llm_generated is False
    assert result.references == []
    assert "证据" in result.response


def test_all_filtered_short_circuits_before_answer_generation():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "rag.test":
            return httpx.Response(200, json={"status": "success", "data": {"chunks": CHUNKS}})
        assert request.url.host == "rerank.test"
        return httpx.Response(200, json={"results": [
            {"index": 0, "relevance_score": 0.02}, {"index": 1, "relevance_score": 0.01}]})

    result = run(handler)
    assert len(calls) == 2
    assert result.llm_generated is False
    assert result.references == []


@pytest.mark.parametrize("host, expected_calls", [("rag.test", 1), ("rerank.test", 2), ("answer.test", 3)])
def test_upstream_failure_stops_pipeline_instead_of_claiming_no_evidence(host, expected_calls):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == host:
            return httpx.Response(503)
        if request.url.host == "rag.test":
            return httpx.Response(200, json={"status": "success", "data": {"chunks": CHUNKS}})
        return httpx.Response(200, json={"results": [
            {"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]})

    with pytest.raises(UpstreamError) as error:
        run(handler)
    assert error.value.status_code == 502
    assert len(calls) == expected_calls


@pytest.mark.parametrize("kind, status", [("timeout", 504), ("transport_error", 503), ("invalid_response", 502)])
def test_stage_error_status_mapping(kind, status):
    with pytest.raises(UpstreamError) as error:
        qa_pipeline.require_stage_success({"error_kind": kind}, "检索")
    assert error.value.status_code == status
    assert error.value.stage == "检索"
