import json

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.lightrag_client import LightRAGClient, UpstreamError


ANSWER = {"response": "需要导师与部门负责人审批。[1]", "references": [
    {"reference_id": "1", "file_path": "intern_policy.md", "content": ["超过1个工作日需要共同审批"]},
    {"reference_id": "2", "file_path": "other.md", "content": []},
], "response_time": 1.5, "llm_generated": True}
SETTINGS = Settings("http://upstream.test/rag", "test-secret")


def test_sends_question_with_key_and_preserves_evidence():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == "http://upstream.test/rag/query"
        assert request.method == "POST"
        assert request.headers["X-API-Key"] == "test-secret"
        payload = json.loads(request.content)
        assert payload["query"] == "请假2天谁审批？"
        assert payload["include_references"] is True
        assert payload["include_chunk_content"] is True
        assert payload["mode"] == "naive"
        assert payload["enable_rerank"] is False
        assert payload["only_need_context"] is False
        assert request.extensions["timeout"]["connect"] == 5
        assert request.extensions["timeout"]["read"] == 120
        return httpx.Response(200, json=ANSWER)
    result = LightRAGClient(SETTINGS, transport=httpx.MockTransport(handler)).ask("请假2天谁审批？")
    assert result.model_dump() == ANSWER
    assert len(calls) == 1


@pytest.mark.parametrize("kind,status", [("timeout",504), ("connection",503), ("auth",502), ("server",502), ("redirect",502), ("json",502), ("schema",502)])
def test_failures_are_safe_and_not_retried(kind, status):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret", request=request)
        if kind == "connection":
            raise httpx.ConnectError("test-secret", request=request)
        if kind in ("auth", "server", "redirect"):
            return httpx.Response({"auth":403,"server":500,"redirect":302}[kind], text="test-secret")
        if kind == "json":
            return httpx.Response(200, text="test-secret")
        return httpx.Response(200, json={"response": 123, "references": "test-secret"})
    with pytest.raises(UpstreamError) as error:
        LightRAGClient(SETTINGS, transport=httpx.MockTransport(handler)).ask("测试问题")
    assert error.value.status_code == status
    assert "test-secret" not in str(error.value)
    assert len(calls) == 1


def test_route_returns_answer_using_real_client_with_test_transport(monkeypatch):
    monkeypatch.setattr(main, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(main, "LightRAGClient", lambda settings: LightRAGClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=ANSWER))))
    with TestClient(main.app) as client:
        response = client.post("/ask", json={"question": "请假2天谁审批？"})
    assert response.status_code == 200
    assert response.json() == ANSWER


def test_invalid_question_does_not_even_load_configuration(monkeypatch):
    def fail():
        pytest.fail("Invalid input must not read configuration or call upstream")
    monkeypatch.setattr(main, "load_settings", fail)
    with TestClient(main.app) as client:
        assert client.post("/ask", json={"question": "   "}).status_code == 422


def test_route_maps_timeout_to_504(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("test-secret", request=request)
    monkeypatch.setattr(main, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(main, "LightRAGClient", lambda settings: LightRAGClient(settings, transport=httpx.MockTransport(handler)))
    with TestClient(main.app) as client:
        response = client.post("/ask", json={"question": "测试问题"})
    assert response.status_code == 504
    assert "test-secret" not in response.text
