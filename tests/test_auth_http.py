import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth_config import AuthSettings
from app.auth_schemas import LoginRequest
from app.config import ConfigurationError


@pytest.fixture
def client(monkeypatch):
    from app import auth_http
    from fastapi import APIRouter

    monkeypatch.setattr(auth_http, "load_auth_settings", lambda: AuthSettings("http://127.0.0.1:8001", False, 7200))
    router = APIRouter(route_class=auth_http.AuthRoute)
    @router.post("/auth/login")
    def probe(payload: LoginRequest):
        return {"accepted": True}
    application = FastAPI()
    application.include_router(router)
    with TestClient(application) as test_client:
        yield test_client


@pytest.mark.parametrize("origin", [None, "null", "https://attacker.example", "http://127.0.0.1:8001.attacker.example"])
def test_bad_origin_rejected_before_login(client, origin):
    headers = {} if origin is None else {"Origin": origin}
    response = client.post("/auth/login", headers=headers, json={"username": "alice", "password": "123456"})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_only_json_is_accepted(client):
    response = client.post("/auth/login", headers={"Origin": "http://127.0.0.1:8001"}, data={"password": "123456"})
    assert response.status_code == 415


def test_validation_errors_never_echo_input(client):
    response = client.post("/auth/login", headers={"Origin": "http://127.0.0.1:8001"}, json={"username": "alice", "password": "SENSITIVE-LONG-PASSWORD"})
    assert response.status_code == 422
    assert "SENSITIVE" not in response.text
    assert "input" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_invalid_configuration_fails_closed(client, monkeypatch):
    from app import auth_http
    def fail():
        raise ConfigurationError("private-value")
    monkeypatch.setattr(auth_http, "load_auth_settings", fail)
    response = client.post("/auth/login", json={"username": "alice", "password": "123456"})
    assert response.status_code == 503
    assert "private-value" not in response.text
