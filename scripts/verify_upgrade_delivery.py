"""Read-only deployed acceptance; logs no credentials and makes zero model requests."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4
from dotenv import dotenv_values
import httpx2 as httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    base = 'http://127.0.0.1:8005'
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError('Acceptance failed: '+name)
    folder = ROOT/'evaluation/upgrade'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_deployment_'+uuid4().hex[:8])
    folder.mkdir()
    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=15) as client:
            check('health_liveness', client.get('/health').status_code == 200)
            page = client.get('/workspace/')
            check('react_bundle_entry', page.status_code == 200 and '/workspace/assets/' in page.text)
            check('legacy_entry_retained', client.get('/').status_code == 200)
            check('unauthenticated_product_denied', client.get('/api/v1/conversations').status_code == 401)
            check('unauthenticated_admin_denied', client.get('/api/v1/admin/reports').status_code == 401)
            response = client.post('/auth/login', headers={'Origin': base}, json={
                'username': values['UPGRADE_ADMIN_USERNAME'], 'password': values['UPGRADE_ADMIN_PASSWORD']})
            check('actual_cookie_login', response.status_code == 200)
            check('http_only_cookie', 'httponly' in response.headers.get('set-cookie', '').lower())
            check('isolated_cookie_name', 'doctrace_upgrade_session=' in response.headers.get('set-cookie', ''))
            identity = client.get('/api/v1/me')
            check('actual_admin_role', identity.status_code == 200 and identity.json()['data']['role'] == 'admin')
            reports = client.get('/api/v1/admin/reports')
            check('real_reports_list', reports.status_code == 200 and len(reports.json()['data']['items']) >= 6)
            for item in reports.json()['data']['items']:
                check('report_'+item['id'], client.get('/api/v1/admin/reports/'+item['id']).status_code == 200)
            for suffix in ('stats', 'documents', 'tasks'):
                check('admin_'+suffix, client.get('/api/v1/admin/'+suffix).status_code == 200)
            check('personal_conversations', client.get('/api/v1/conversations?limit=2&offset=0').status_code == 200)
            check('report_traversal_denied', client.get('/api/v1/admin/reports/.env').status_code == 404)
            logout = client.post('/auth/logout', headers={'Origin': base}, json={})
            check('logout', logout.status_code == 204)
            check('revoked_cookie_denied', client.get('/api/v1/me').status_code == 401)
        status = 'passed'
    except Exception:
        status = 'failed'
        raise
    finally:
        (folder/'report.json').write_text(json.dumps({'status': status, 'checks': checks,
            'provider_calls': 0, 'database': 'doctrace_upgrade', 'port': 8005,
            'scope': 'Actual deployed HTTP, Cookie, MySQL and read-only reports; no new question generated.'}, indent=2), encoding='utf-8')
        print('Deployment checks:', len(checks), 'Report:', folder/'report.json')


if __name__ == '__main__':
    main()
