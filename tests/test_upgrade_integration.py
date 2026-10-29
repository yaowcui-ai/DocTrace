from pathlib import Path

from fastapi.testclient import TestClient


def test_product_routes_are_registered_in_real_application():
    from app.main import app
    # FastAPI's included routers may be lazy wrapper objects; inspect the public contract.
    paths = set(app.openapi()['paths'])
    assert '/api/v1/conversations' in paths
    assert '/api/v1/admin/documents' in paths


def test_react_entry_is_served_or_explicitly_requires_build():
    from app.main import app
    with TestClient(app) as client:
        response = client.get('/workspace/')
    built = Path(__file__).resolve().parents[1]/'frontend/dist/index.html'
    assert response.status_code == (200 if built.exists() else 503)
    if built.exists():
        assert '/workspace/assets/' in response.text


def test_versioned_api_remains_authenticated_and_noncacheable():
    from app.main import app
    with TestClient(app) as client:
        response = client.get('/api/v1/conversations')
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'
