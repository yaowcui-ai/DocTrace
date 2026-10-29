from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def test_reports_need_admin_before_reading_any_files():
    from app.upgrade_reports import router
    from app.product.api import require_admin
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(router)
    def denied():
        raise HTTPException(403, '需要管理员权限。')
    app.dependency_overrides[require_admin] = denied
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/reports').status_code == 403
        assert client.get('/api/v1/admin/reports/unknown').status_code == 403


def test_report_registry_is_explicit_and_prevents_symlink_escape(tmp_path, monkeypatch):
    import app.upgrade_reports as reports
    from app.product.api import require_admin
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[require_admin] = lambda: object()
    monkeypatch.setattr(reports, 'REPORT_DIR', tmp_path)
    monkeypatch.setattr(reports, 'REGISTRY', {'baseline': ('base.json', 'Original baseline')})
    (tmp_path/'base.json').write_text('{"cases":20,"provider_calls":0}', encoding='utf-8')
    (tmp_path/'private.json').write_text('{"password":"should-never-be-served"}', encoding='utf-8')
    with TestClient(app) as client:
        response = client.get('/api/v1/admin/reports')
        assert response.status_code == 200
        assert [item['id'] for item in response.json()['data']['items']] == ['baseline']
        assert client.get('/api/v1/admin/reports/baseline').json()['data']['report']['cases'] == 20
        assert client.get('/api/v1/admin/reports/private').status_code == 404
        assert 'should-never-be-served' not in client.get('/api/v1/admin/reports').text
        assert client.get('/api/v1/admin/reports/baseline').headers['cache-control'] == 'no-store'


def test_missing_report_is_explicit_not_fake_success(tmp_path, monkeypatch):
    import app.upgrade_reports as reports
    from app.product.api import require_admin
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[require_admin] = lambda: object()
    monkeypatch.setattr(reports, 'REPORT_DIR', tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/reports/baseline').status_code == 404
