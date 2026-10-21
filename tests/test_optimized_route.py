import json

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.answer_config import AnswerSettings
from app.config import ConfigurationError, Settings
from app.facet_policy import POLICY_VERSION
from app.medium_config import MediumSettings


@pytest.fixture
def configured(monkeypatch, record_engine):
    monkeypatch.setattr(main, "create_db_engine", lambda settings: record_engine)
    monkeypatch.setattr(main, "load_settings", lambda: Settings("http://rag.test", "service-key"))
    monkeypatch.setattr(main, "load_medium_settings", lambda: MediumSettings(
        Settings("http://rag.test", "service-key"), 40000, "test_corpus"), raising=False)
    monkeypatch.setattr(main, "load_answer_settings", lambda: AnswerSettings(
        "https://answer.test/chat/completions", "answer", "answer-key"), raising=False)
    def forbidden():
        pytest.fail("The medium route must not load legacy rerank or character-filter settings")
    monkeypatch.setattr(main, "load_rerank_settings", forbidden, raising=False)
    monkeypatch.setattr(main, "load_pipeline_settings", forbidden, raising=False)


@pytest.mark.parametrize("scenario", ["success", "low_scores", "fallback", "empty", "upstream_failure", "missing_policy"])
def test_optimized_route_runs_real_orchestration_with_mock_providers(monkeypatch, configured, scenario):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "rag.test":
            if scenario == "upstream_failure":
                return httpx.Response(503)
            assert json.loads(request.content)=={
                "query":"Question", "mode":"mix", "enable_rerank":False, "max_total_tokens":40000,
            }
            assert request.headers['X-API-Key']=='service-key'
            chunks=[] if scenario=="empty" else [
                {"chunk_id":"A", "reference_id":"9", "file_path":"a.md", "content":"Rule A",
                 "rerank_score":0.01 if scenario=="low_scores" else 0.9}]
            metadata=None if scenario=="missing_policy" else {
                "version":POLICY_VERSION,
                "strategy":"fallback_original" if scenario=="fallback" else "whole_query_rerank",
            }
            return httpx.Response(200,json={"status":"success","data":{"chunks":chunks},
                                           "metadata":{"doctrace_policy":metadata}})
        assert request.url.host == "answer.test", "Unexpected duplicate rerank request"
        evidence = json.loads(json.loads(request.content)["messages"][1]["content"])["evidence"]
        assert evidence[0]["reference_id"] == "1"
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "Rule A [1]"}, "finish_reason": "stop"}]})

    monkeypatch.setattr(main, "make_qa_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler)), raising=False)
    with TestClient(main.app) as client:
        response = client.post("/ask/optimized", json={"question": "  Question  ", "mode":"mix"})
    if scenario in ("upstream_failure", "missing_policy"):
        assert response.status_code == 502
        assert response.json()["detail"]["stage"] == ("检索" if scenario=="upstream_failure" else "检索策略")
        assert len(calls) == 1
    else:
        assert response.status_code == 200
        assert response.json()["llm_generated"] is (scenario != "empty")
        assert len(calls) == (1 if scenario == "empty" else 2)
        if scenario != "empty":
            assert response.json()["retrieval"]["degraded"] is (scenario=="fallback")
            assert response.json()["retrieval"]["policy_version"]==POLICY_VERSION


def test_invalid_question_is_rejected_before_configuration(monkeypatch):
    def fail():
        pytest.fail("Invalid input must not enter the handler")

    monkeypatch.setattr(main, "load_medium_settings", fail, raising=False)
    monkeypatch.setattr(main, "load_settings", fail)
    with TestClient(main.app) as client:
        response = client.post("/ask/optimized", json={"question": "   "})
    assert response.status_code == 422


def test_invalid_configuration_is_not_exposed(monkeypatch, configured):
    def fail():
        raise ConfigurationError("secret-value")

    monkeypatch.setattr(main, "load_answer_settings", fail, raising=False)
    with TestClient(main.app) as client:
        response = client.post("/ask/optimized", json={"question": "Question"})
    assert response.status_code == 503
    assert "secret-value" not in response.text
