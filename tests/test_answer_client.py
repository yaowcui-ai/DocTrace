import json

import httpx2 as httpx
import pytest

from app.answer_client import collect_answer
from app.answer_config import AnswerSettings
from app.answer_prompt import SYSTEM_PROMPT
from app.context_builder import build_evidence_context


SETTINGS = AnswerSettings("https://answer.test/chat/completions", "test-model", "test-secret")
BUNDLE = build_evidence_context([
    {"chunk_id": "selected-A", "file_path": "policy.md", "content": "Give six business days notice."}])
BODY = {"choices": [{"message": {"role": "assistant", "content": "Give six business days notice. [1]"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10}}


def test_selected_evidence_is_sent_and_program_references_are_preserved():
    def handler(request):
        assert str(request.url) == SETTINGS.answer_url
        assert request.headers["Authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
        data = json.loads(payload["messages"][1]["content"])
        assert data["question"] == "How much notice?"
        assert data["evidence"] == json.loads(BUNDLE["context"])
        return httpx.Response(200, json=BODY)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = collect_answer(client, SETTINGS, "How much notice?", BUNDLE)
    assert record["error_kind"] is None
    assert record["raw_response"] == BODY
    assert record["result"]["references"] == BUNDLE["references"]
    assert record["result"]["llm_generated"] is True
    assert record["result"]["response"] == BODY["choices"][0]["message"]["content"]
    assert "test-secret" not in json.dumps(record)


@pytest.mark.parametrize("kind, expected", [
    ("timeout", "timeout"), ("connection", "transport_error"),
    ("http", "http_error"), ("json", "invalid_response"),
    ("missing", "invalid_response"), ("empty", "invalid_response"),
    ("truncated", "incomplete_response"),
])
def test_failures_do_not_become_success_or_trigger_retries(kind, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ConnectTimeout("test-secret", request=request)
        if kind == "connection":
            raise httpx.ConnectError("test-secret", request=request)
        if kind == "http":
            return httpx.Response(402, json={"error": "insufficient balance"})
        if kind == "json":
            return httpx.Response(200, text="invalid JSON")
        if kind == "missing":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"choices": [{
            "message": {"role": "assistant", "content": "partial" if kind == "truncated" else " "},
            "finish_reason": "length" if kind == "truncated" else "stop"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = collect_answer(client, SETTINGS, "Question", BUNDLE)
    assert len(calls) == 1
    assert record["error_kind"] == expected
    assert record["result"] is None
    assert "test-secret" not in json.dumps(record)
    if kind == "timeout":
        assert record["transport_exception_type"] == "ConnectTimeout"


def test_empty_context_never_calls_answer_model():
    def fail(request):
        pytest.fail("Empty evidence must not be sent to the model")

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        record = collect_answer(client, SETTINGS, "Question", build_evidence_context([]))
    assert record["http_status"] is None
    assert record["error_kind"] == "invalid_input"
    assert record["result"] is None
