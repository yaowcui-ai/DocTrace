import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import AskRequest


def test_question_removes_surrounding_whitespace():
    request = AskRequest(question="  GitLab 的休假申请有哪些要求？  ")

    assert request.question == "GitLab 的休假申请有哪些要求？"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": ""},
        {"question": " \n\t "},
        {"question": 42},
        {"question": None},
        {"question": "x" * 2001},
        {"question": "GitLab 的休假申请有哪些要求？", "unexpected": True},
    ],
)
def test_invalid_question_is_rejected_before_answer_handling(payload):
    with TestClient(app) as client:
        response = client.post("/ask", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "body"


def test_valid_question_with_missing_configuration_returns_503(monkeypatch):
    from app import main
    from app.config import ConfigurationError

    def missing_configuration():
        raise ConfigurationError("LIGHTRAG_API_KEY is required.")

    monkeypatch.setattr(main, "load_settings", missing_configuration)
    with TestClient(app) as client:
        response = client.post("/ask", json={"question": "GitLab 的休假申请有哪些要求？"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "问答服务配置不完整或无效，请检查后端配置。"
    }
