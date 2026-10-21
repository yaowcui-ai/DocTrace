"""User page delivery is independent of database and model availability."""
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from app import main


@pytest.fixture
def web_client(monkeypatch):
    engine = Mock()
    monkeypatch.setattr(main, "create_db_engine", lambda settings: engine)

    def forbidden(*args, **kwargs):
        pytest.fail("Opening the page must not query records or call models")
    for name in ("get_qa_record", "list_qa_records", "make_qa_client", "run_medium_qa_pipeline"):
        monkeypatch.setattr(main, name, forbidden)
    with TestClient(main.app) as client:
        yield client
    engine.connect.assert_not_called()


def test_home_returns_user_page_instead_of_json(web_client):
    response = web_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="zh-CN">' in response.text
    assert "DocTrace" in response.text
    assert 'href="/static/styles.css"' in response.text
    assert 'type="module" src="/static/history.js"' in response.text
    assert 'type="module" src="/static/question.js"' in response.text
    assert 'id="history-controls"' in response.text
    assert 'id="question"' in response.text
    assert 'id="history-list"' in response.text


def test_stylesheet_is_served_as_css(web_client):
    response = web_client.get("/static/styles.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".workspace" in response.text


@pytest.mark.parametrize("name", ["history.js", "history-view.js", "record-detail.js", "record-view.js", "conversation.js", "question.js", "question-view.js", "markdown.js", "vendor/marked.esm.js", "vendor/purify.es.mjs"])
def test_history_scripts_are_available_without_backend_calls(web_client, name):
    response = web_client.get("/static/" + name)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


@pytest.mark.parametrize("name", ["examples.js", "examples-view.js"])
def test_public_example_scripts_are_served(web_client, name):
    response = web_client.get("/static/" + name)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/static/.env", "/static/%2e%2e/.env"])
def test_static_mount_does_not_expose_backend_configuration(web_client, path):
    assert web_client.get(path).status_code == 404
