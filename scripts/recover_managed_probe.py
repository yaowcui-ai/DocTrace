"""Recover already persisted managed smoke results via GET; never ask or reindex."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    from dotenv import dotenv_values
    import httpx2 as httpx
    values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    with httpx.Client(base_url='http://127.0.0.1:8005', trust_env=False, timeout=10,
                      headers={'Origin': 'http://127.0.0.1:8005'}) as client:
        response = client.post('/auth/login', json={'username': values['UPGRADE_ADMIN_USERNAME'], 'password': values['UPGRADE_ADMIN_PASSWORD']})
        response.raise_for_status()
        conversations = client.get('/api/v1/conversations', params={'q': '真实托管库入库与问答验收'}).json()['data']['items']
        if not conversations:
            raise RuntimeError('No saved smoke conversation found; no new request sent')
        detail = client.get('/api/v1/conversations/'+conversations[0]['id'])
        detail.raise_for_status()
        result = detail.json()['data']
        output = ROOT/'evaluation/upgrade/live/managed_recovery_20261028.json'
        with output.open('x', encoding='utf-8') as stream:
            json.dump({'kind': 'read_only_recovery_after_report_serialization_error', 'new_model_calls': 0,
                'original_check': '20261028T072847Z_43f38705', 'conversation': result}, stream, ensure_ascii=False, indent=2)
        for message in result['messages']:
            print('Saved message:', message['request_id'], message['status'], 'references:', len(message['references']))
            print('Answer:', message['answer'])
        print('Report:', output)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
