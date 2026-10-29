"""Bounded real-HTTP/MySQL benchmark with a synthetic provider; no provider requests."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered)-1)*percent/100
    lo, hi = math.floor(position), math.ceil(position)
    return round(ordered[lo]+(ordered[hi]-ordered[lo])*(position-lo), 6)


def summarize(records, wall_seconds):
    completed = [r['elapsed_seconds'] for r in records if r['completed']]
    count = len(records)
    return {'attempted': count, 'http_successes': sum(r['status_code'] == 200 for r in records),
        'completed': len(completed), 'failures': count-len(completed),
        'failure_rate': (count-len(completed))/count if count else None,
        'http_status_counts': dict(Counter(str(r['status_code']) if r['status_code'] is not None else 'transport_error' for r in records)),
        'attempted_requests_per_second': count/wall_seconds,
        'completed_requests_per_second': len(completed)/wall_seconds,
        'completed_latency_seconds': {'p50': percentile(completed, 50), 'p95': percentile(completed, 95)},
        'all_attempt_latency_seconds': {'p50': percentile([r['elapsed_seconds'] for r in records], 50),
            'p95': percentile([r['elapsed_seconds'] for r in records], 95)}}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--requests-per-level', type=int, choices=range(1, 21), default=20)
    return parser.parse_args(argv)


def request_inputs(conversations, concurrency, run_id):
    return [{'conversation_id': cid, 'idempotency_key': str(uuid4()), 'body': {
        'question': f'[SYNTHETIC LOAD {run_id} c={concurrency} n={index}] What is the fixture policy?',
        'mode': 'naive', 'knowledge_base': 'frozen'}} for index, cid in enumerate(conversations)]


async def execute(base, folder, password, count):
    import httpx
    rows = []
    async with httpx.AsyncClient(base_url=base, timeout=30, trust_env=False, headers={'Origin': base}) as client:
        response = await client.post('/auth/login', json={'username': 'load_' + folder.name[-8:], 'password': password})
        response.raise_for_status()
        client.headers['X-DocTrace-User-ID'] = response.json()['user_id']
        for concurrency in (1, 5, 10, 20):
            conversation_ids = []
            for _ in range(count):
                response = await client.post('/api/v1/conversations', json={'title': f'Synthetic load c={concurrency}'})
                response.raise_for_status()
                conversation_ids.append(response.json()['data']['id'])
            operations = request_inputs(conversation_ids, concurrency, folder.name)
            semaphore = asyncio.Semaphore(concurrency)
            async def ask(operation):
                async with semaphore:
                    started = time.perf_counter()
                    code, completed, error = None, False, None
                    try:
                        answer = await client.post('/api/v1/conversations/'+operation['conversation_id']+'/messages',
                            json=operation['body'], headers={'Idempotency-Key': operation['idempotency_key']})
                        code = answer.status_code
                        completed = code == 200 and answer.json().get('data', {}).get('status') == 'completed'
                    except (httpx.HTTPError, ValueError) as exception:
                        error = type(exception).__name__
                    return {'status_code': code, 'completed': completed, 'error_type': error,
                        'elapsed_seconds': round(time.perf_counter()-started, 6), 'operation': operation}
            started = time.perf_counter()
            measured = await asyncio.gather(*(ask(operation) for operation in operations))
            seconds = time.perf_counter()-started
            rows.append({'concurrency': concurrency, 'wall_seconds': seconds,
                'summary': summarize(measured, seconds), 'records': measured})
    return rows


def main():
    args = parse_args()
    if not args.execute:
        print('Preview: synthetic-provider HTTP/MySQL benchmark, max 80 operations; use --execute. No providers called.')
        return 0
    from dotenv import dotenv_values
    from app.database import create_db_engine
    from app.database_config import DatabaseSettings
    from app.users import create_user
    import secrets
    values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    if values.get('MYSQL_DATABASE') != 'doctrace_upgrade' or values.get('MYSQL_PORT') != '3310':
        raise RuntimeError('Only the isolated upgrade database is permitted')
    folder = ROOT/'evaluation/upgrade/performance'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    password = secrets.token_urlsafe(20)
    engine = create_db_engine(DatabaseSettings('127.0.0.1', 3310, 'doctrace_upgrade', values['MYSQL_USER'], values['MYSQL_PASSWORD']))
    create_user(engine, username='load_'+folder.name[-8:], password=password)
    engine.dispose()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    base, child = f'http://127.0.0.1:{port}', None
    try:
        with (folder/'server.log').open('wb') as log:
            child = subprocess.Popen([sys.executable, 'tests/support/product_mysql_server.py', str(port)], cwd=ROOT,
                env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONIOENCODING': 'utf-8'}, stdout=log, stderr=subprocess.STDOUT)
            import httpx
            with httpx.Client(timeout=1, trust_env=False) as client:
                for _ in range(80):
                    if child.poll() is not None:
                        raise RuntimeError('Isolated fixture stopped; inspect its log')
                    try:
                        if client.get(base+'/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.25)
                else:
                    raise RuntimeError('Fixture startup deadline exceeded')
            levels = asyncio.run(execute(base, folder, password, args.requests_per_level))
            stats = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', 'doctrace-upgrade-mysql-1'],
                capture_output=True, text=True, check=True).stdout
            report = {'kind': 'synthetic_provider_real_http_mysql', 'created_at': datetime.now(timezone.utc).isoformat(),
                'provider_calls': 0, 'database': 'doctrace_upgrade', 'database_port': 3310,
                'hardware': {'system': platform.platform(), 'processor': platform.processor(), 'logical_cpus': os.cpu_count()},
                'protocol': {'levels': [1,5,10,20], 'requests_per_level': args.requests_per_level,
                    'mock_provider_seconds': .1, 'max_paid_work_concurrency': 2, 'per_account_concurrency': 1},
                'levels': levels, 'database_resource_snapshot_end': stats,
                'limitations': ['Single account; application backpressure expected, 429 retained as failure.',
                    'Synthetic provider replaces retrieval/rerank/generation; not real RAG throughput or model latency.',
                    'One short batch per level; end resource snapshot is not peak resource measurement or production capacity.']}
            (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps([{'concurrency': r['concurrency'], **r['summary']} for r in levels], indent=2))
            print('Report:', folder/'report.json')
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
