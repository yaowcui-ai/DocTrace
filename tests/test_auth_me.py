"""Current identity is derived from a server-side session, never from a user ID."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth_config import AuthSettings, SESSION_COOKIE_NAME
from app.sessions import create_session, revoke_session
from app.users import create_user


@pytest.fixture
def identity_client(session_engine, monkeypatch):
    from app import auth_http, auth_routes

    monkeypatch.setattr(auth_http, "load_auth_settings", lambda: AuthSettings("http://127.0.0.1:8001", False, 7200))
    application = FastAPI()
    application.state.db_engine = session_engine
    application.include_router(auth_routes.router)
    user_id = create_user(session_engine, username="alice", password="Al1ce!23")
    token, _ = create_session(session_engine, user_id=user_id)
    with TestClient(application, base_url="http://127.0.0.1:8001") as client:
        client.cookies.set(SESSION_COOKIE_NAME, token)
        yield client, user_id, token, auth_routes


def test_valid_cookie_returns_only_public_identity(identity_client):
    client, user_id, token, _ = identity_client
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == {"user_id": user_id, "username": "alice"}
    assert token not in response.text
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("kind", ["missing", "malformed", "unknown", "expired", "revoked", "disabled"])
def test_invalid_session_denies_identity(identity_client, session_engine, kind):
    client, _, token, _ = identity_client
    if kind == "missing":
        client.cookies.clear()
    elif kind in {"malformed", "unknown"}:
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, "bad" if kind == "malformed" else "x" * 43)
    elif kind == "revoked":
        revoke_session(session_engine, token)
    elif kind == "disabled":
        with session_engine.begin() as conn:
            conn.execute(text("UPDATE app_users SET is_active=0"))
    elif kind == "expired":
        with session_engine.begin() as conn:
            conn.execute(text("UPDATE app_sessions SET created_at='2000-01-01 00:00:00', expires_at='2000-01-02 00:00:00'"))
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "请先登录，或重新登录。"}
    assert response.headers["cache-control"] == "no-store"


def test_database_failure_is_not_anonymous(identity_client, monkeypatch):
    client, _, _, routes = identity_client
    def fail(*args, **kwargs):
        raise SQLAlchemyError("private-database-details")
    monkeypatch.setattr(routes, "get_session_user", fail)
    response = client.get("/auth/me")
    assert response.status_code == 503
    assert "private-database-details" not in response.text


def test_database_not_configured(identity_client):
    client, _, _, _ = identity_client
    client.app.state.db_engine = None
    assert client.get("/auth/me").status_code == 503


def test_client_cannot_choose_another_identity(identity_client, session_engine):
    client, user_id, _, _ = identity_client
    other_id = create_user(session_engine, username="bob", password="B0b!1234")
    response = client.get("/auth/me", params={"user_id": other_id}, headers={"X-User-ID": other_id})
    assert response.status_code == 200
    assert response.json()["user_id"] == user_id
