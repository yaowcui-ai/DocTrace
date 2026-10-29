from fastapi.testclient import TestClient


def test_oversized_auth_body_is_rejected_before_validation_or_database():
    from app.main import app
    with TestClient(app) as client:
        response = client.post('/auth/login', content=b'x'*40000, headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert response.headers['cache-control'] == 'no-store'


def test_chunked_upload_cannot_bypass_byte_limit():
    from app.main import app
    with TestClient(app) as client:
        response = client.post('/api/v1/admin/documents', content=iter([b'x'*700000, b'y'*700000]),
            headers={'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8001'})
    assert response.status_code == 413
