"""One real managed-document index + one real product answer, with bounded polling."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('Preview: one small public-policy excerpt index and one managed answer; use --execute.')
        return 0
    from dotenv import dotenv_values
    values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    if values.get('MYSQL_DATABASE') != 'doctrace_upgrade':
        raise RuntimeError('Wrong isolated database')
    os.environ.update({key: value for key, value in values.items() if value is not None})
    import httpx2 as httpx
    from app.database_config import load_database_settings
    from app.database import create_db_engine
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.upstream import ManagedClient, ManagedSettings
    from app.knowledge.worker import run_once
    source = ROOT/'data/gitlab_hr/v3/cleaned/hr_contracts_probation_periods.md'
    quote = 'A team member cannot have more than three fixed term contracts with the same employer in a row. If a fourth contract is offered by GitLab then it must be a permanent one.'
    assert quote in source.read_text(encoding='utf-8')
    content = '# GitLab 合同政策演示节选\n\n来源：https://handbook.gitlab.com/handbook/people-group/contracts-probation-periods/\n\n这是冻结政策原文节选，仅用于演示本系统入库与证据追溯，不是完整政策或当前法律建议。\n\n'+quote
    folder = ROOT/'evaluation/upgrade/live'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_managed_'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    report = {'kind': 'real_managed_index_product_smoke', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'content': content, 'status': 'started', 'events': [], 'automatic_mutation_retries': 0}
    def save():
        from fastapi.encoders import jsonable_encoder
        (folder/'report.json').write_text(json.dumps(jsonable_encoder(report), ensure_ascii=False, indent=2), encoding='utf-8')
    engine = create_db_engine(load_database_settings())
    try:
        managed = ManagedClient(ManagedSettings('http://127.0.0.1:9631', values['MANAGED_LIGHTRAG_API_KEY']))
        managed.verify()
        repo = KnowledgeRepository(engine)
        with httpx.Client(base_url='http://127.0.0.1:8005', timeout=httpx.Timeout(120, connect=5), trust_env=False,
                          headers={'Origin': 'http://127.0.0.1:8005'}) as client:
            login = client.post('/auth/login', json={'username': values['UPGRADE_ADMIN_USERNAME'], 'password': values['UPGRADE_ADMIN_PASSWORD']})
            login.raise_for_status()
            client.headers['X-DocTrace-User-ID'] = login.json()['user_id']
            document = client.post('/api/v1/admin/documents', json={'filename': 'gitlab_contract_excerpt.md', 'content': content})
            document.raise_for_status()
            doc = document.json()['data']
            report['doc_id'] = doc['doc_id']
            queued = client.post('/api/v1/admin/documents/'+doc['doc_id']+'/index', json={})
            queued.raise_for_status()
            report['enqueue'] = queued.json()['data']
            save()
            for _ in range(30):
                run_once(repo, managed)
                state = repo.get(doc['doc_id'])
                report['events'].append({'time': datetime.now(timezone.utc).isoformat(), 'state': state['state'], 'failure': state.get('failure')})
                save()
                print('Managed indexing:', state['state'], flush=True)
                if state['state'] in {'processed', 'failed', 'submission_unknown'}:
                    break
                time.sleep(2)
            report['document'] = state
            if state['state'] != 'processed':
                report['status'] = 'index_not_completed_no_resubmission'
                save()
                print('Report:', folder/'report.json')
                return 1
            conversation = client.post('/api/v1/conversations', json={'title': '真实托管库入库与问答验收'})
            conversation.raise_for_status()
            cid = conversation.json()['data']['id']
            key = str(uuid4())
            payload = {'question': '根据合同政策节选，同一雇主连续提供第四份合同时必须是什么合同类型？', 'mode': 'naive', 'knowledge_base': 'managed'}
            started = time.perf_counter()
            answer = client.post('/api/v1/conversations/'+cid+'/messages', json=payload, headers={'Idempotency-Key': key})
            report['ask'] = {'http_status': answer.status_code, 'seconds': round(time.perf_counter()-started, 3), 'payload': payload,
                'result': answer.json(), 'conversation_id': cid, 'operation_key': key}
            report['status'] = 'completed' if answer.status_code == 200 and answer.json().get('data', {}).get('status') == 'completed' else 'answer_not_completed'
            save()
            print('Managed answer HTTP:', answer.status_code, 'status:', report['status'])
            print('Report:', folder/'report.json')
            return 0 if report['status'] == 'completed' else 1
    finally:
        engine.dispose()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
