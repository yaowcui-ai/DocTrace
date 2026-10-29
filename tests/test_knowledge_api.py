import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth_routes import read_current_user
from app.auth_schemas import CurrentUserResponse
from test_knowledge_repository import repo


@pytest.fixture
def api(repo, monkeypatch):
    from app.knowledge.api import router
    from app.product.api import require_admin
    monkeypatch.setenv('AUTH_ALLOWED_ORIGIN', 'http://127.0.0.1:8001')
    app = FastAPI()
    app.state.db_engine = repo.engine
    app.include_router(router)
    with TestClient(app) as http:
        yield app, http, require_admin


def test_anonymous_cannot_read_document_or_tasks(api):
    _, http, _ = api
    for path in ['/documents', '/documents/00000000-0000-4000-8000-000000000001', '/tasks']:
        response = http.get('/api/v1/admin' + path)
        assert response.status_code == 401
        assert response.headers['Cache-Control'] == 'no-store'


def test_admin_document_roundtrip_strict_json_origin_and_validation(api):
    app, http, require_admin = api
    app.dependency_overrides[require_admin] = lambda: {'user_id': 'admin'}
    base = '/api/v1/admin/documents'
    assert http.post(base, json={'filename': 'a.md', 'content': 'policy'}).status_code == 403
    assert http.post(base, headers={'Origin': 'http://127.0.0.1:8001'}, content='body').status_code == 415
    headers = {'Origin': 'http://127.0.0.1:8001'}
    invalid = http.post(base, headers=headers, json={'filename': '../a.md', 'content': 'secret-content'})
    assert invalid.status_code == 422
    assert 'secret-content' not in invalid.text
    created = http.post(base, headers=headers, json={'filename': 'a.md', 'content': 'policy'}).json()['data']
    doc_id = created['doc_id']
    assert http.get(base + '/' + doc_id).json()['data']['content'] == 'policy'
    assert 'content' not in http.get(base).json()['data'][0]
    changed = http.put(base + '/' + doc_id, headers=headers, json={'filename': 'a.md', 'content': 'new policy'})
    assert changed.json()['data']['version'] == 2
    queued = http.post(base + '/' + doc_id + '/index', headers=headers, json={}).json()['data']
    assert http.get('/api/v1/admin/tasks/' + queued['task_id']).json()['data']['state'] == 'queued'
    assert http.delete(base + '/' + doc_id, headers={**headers, 'Content-Type': 'application/json'}).status_code == 409


def test_missing_role_and_user_role_default_deny_content(api, monkeypatch):
    from app.product import repository
    app, http, _ = api
    app.dependency_overrides[read_current_user] = lambda: CurrentUserResponse(user_id='00000000-0000-4000-8000-000000000001', username='reader')
    for role in ['user', None]:
        monkeypatch.setattr(repository, 'get_role', lambda *a: role)
        response = http.get('/api/v1/admin/documents')
        assert response.status_code == 403
