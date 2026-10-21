import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth_config import AuthSettings, SESSION_COOKIE_NAME
from app.session_tokens import hash_session_token
from app.sessions import SessionUserUnavailable, get_session_user
from app.users import create_user


@pytest.fixture
def login_client(session_engine, monkeypatch):
    from app import auth_routes
    from app import auth_http

    settings = AuthSettings("http://127.0.0.1:8001", False, 7200)
    monkeypatch.setattr(auth_http, "load_auth_settings", lambda: settings)
    application = FastAPI()
    application.state.db_engine = session_engine
    application.include_router(auth_routes.router)
    user_id = create_user(session_engine, username="alice", password="Al1ce!23")
    with TestClient(application, base_url=settings.allowed_origin) as client:
        client.headers["Origin"] = settings.allowed_origin
        yield client, user_id, auth_routes


def test_login_commits_session_and_sets_private_cookie(login_client, session_engine):
    client, user_id, _ = login_client
    response = client.post("/auth/login", json={"username": "alice", "password": "Al1ce!23"})
    assert response.status_code == 200
    assert response.json() == {"user_id": user_id, "username": "alice"}
    token = client.cookies.get(SESSION_COOKIE_NAME)
    assert get_session_user(session_engine, token)["user_id"] == user_id
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert "max-age=7200" in cookie and "expires=" in cookie and "; secure" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert token not in response.text and "Al1ce!23" not in response.text
    with session_engine.connect() as conn:
        assert conn.execute(text("SELECT token_hash FROM app_sessions")).scalar_one() == hash_session_token(token)


@pytest.mark.parametrize("kind", ["wrong_password", "unknown", "disabled"])
def test_login_failures_are_indistinguishable(login_client, session_engine, kind):
    client, _, _ = login_client
    if kind == "disabled":
        with session_engine.begin() as conn:
            conn.execute(text("UPDATE app_users SET is_active=0"))
    response = client.post("/auth/login", json={
        "username": "nobody" if kind == "unknown" else "alice",
        "password": "Wrong!23" if kind == "wrong_password" else "Al1ce!23",
    })
    assert response.status_code == 401
    assert response.json() == {"detail": "用户名或密码不正确，或账户不可用。"}
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    with session_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM app_sessions")).scalar_one() == 0


def test_password_whitespace_is_not_removed(login_client, session_engine):
    client, _, _ = login_client
    create_user(session_engine, username="bob", password=" abcdef ")
    assert client.post("/auth/login", json={"username": "bob", "password": " abcdef "}).status_code == 200


def test_session_failure_does_not_issue_cookie(login_client, monkeypatch):
    client, _, routes = login_client
    def fail(*args, **kwargs):
        raise SQLAlchemyError("private-database-value")
    monkeypatch.setattr(routes, "create_session", fail)
    response = client.post("/auth/login", json={"username": "alice", "password": "Al1ce!23"})
    assert response.status_code == 503
    assert "private-database-value" not in response.text
    assert "set-cookie" not in response.headers


def test_missing_database_is_unavailable(login_client):
    client, _, _ = login_client
    client.app.state.db_engine = None
    assert client.post("/auth/login", json={"username": "alice", "password": "Al1ce!23"}).status_code == 503


def test_authentication_database_error_is_not_bad_password(login_client, monkeypatch):
    client, _, routes = login_client
    def fail(*args, **kwargs):
        raise SQLAlchemyError("private-account-value")
    monkeypatch.setattr(routes, "authenticate_user", fail)
    response = client.post("/auth/login", json={"username": "alice", "password": "Al1ce!23"})
    assert response.status_code == 503
    assert "private-account-value" not in response.text


def test_account_disabled_during_session_creation(login_client, monkeypatch):
    client, _, routes = login_client
    def fail(*args, **kwargs):
        raise SessionUserUnavailable()
    monkeypatch.setattr(routes, "create_session", fail)
    response = client.post("/auth/login", json={"username": "alice", "password": "Al1ce!23"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_https_cookie_uses_secure_and_configured_lifetime(login_client, monkeypatch):
    from app import auth_http
    client, _, _ = login_client
    monkeypatch.setattr(auth_http, "load_auth_settings", lambda: AuthSettings("https://doctrace.example", True, 60))
    response = client.post("/auth/login", headers={"Origin": "https://doctrace.example"}, json={"username": "alice", "password": "Al1ce!23"})
    assert response.status_code == 200
    assert "; Secure" in response.headers["set-cookie"]
    assert "Max-Age=60" in response.headers["set-cookie"]
