from fastapi.testclient import TestClient

from app.main import app


def test_health_is_available_without_model_configuration(monkeypatch):
    monkeypatch.delenv("LLM_BINDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_BINDING_API_KEY", raising=False)
    monkeypatch.setenv("LIGHTRAG_URL", "http://127.0.0.1:1")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok", "service": "DocTrace"}
