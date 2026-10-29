"""Explicit one-time recovery from saved candidate captures, never implicit paid retry."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify_frozen_inputs(root=ROOT):
    dataset = root/'evaluation/upgrade_dataset/internal-test-v1/dataset.json'
    freeze = json.loads((dataset.parent/'freeze.json').read_text(encoding='utf-8'))
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != freeze['dataset_sha256']:
        raise ValueError('Frozen dataset changed')
    for path, expected in freeze['code_sha256'].items():
        if hashlib.sha256((root/path).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen algorithm changed: '+path)
    return freeze['dataset_sha256']


def original_rerank_status(old):
    return old.get('policy', {}).get('whole', {}).get('http_status')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int, default=3, choices=range(1, 41))
    parser.add_argument('--min-interval-seconds', type=int, default=60, choices=range(30, 121))
    parser.add_argument('--case')
    args = parser.parse_args()
    frozen_dataset_hash = verify_frozen_inputs()
    folder = args.run.resolve()
    if not folder.is_relative_to((ROOT/'evaluation/upgrade/new_retrieval').resolve()):
        raise ValueError('Unexpected experiment path')
    eligible = []
    for path in sorted(folder.glob('HR-U*.json')):
        row = json.loads(path.read_text(encoding='utf-8'))
        if args.case and row['case_id'] != args.case:
            continue
        if row.get('status') == 'rerank_failed' and row.get('capture'):
            retries = list((folder/'retries').glob(row['case_id']+'_*.json')) if (folder/'retries').exists() else []
            if not retries:
                eligible.append((path, row))
    print('Eligible captured failures without previous recovery:', len(eligible))
    if not args.execute:
        print('Preview only. Recovery reuses captures; no LightRAG or embedding requests are repeated.')
        return 0
    from app.experiment_budget import ProviderBudget
    from app.facet_policy import rank_with_facets
    from app.rerank_client import collect_rerank
    from app.rerank_config import load_rerank_settings
    import httpx2 as httpx
    budget = ProviderBudget(max_attempts=args.limit, min_interval=args.min_interval_seconds)
    settings = load_rerank_settings()
    (folder/'retries').mkdir(exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(90, connect=5), trust_env=False) as client:
        for path, old in eligible[:args.limit]:
            if budget.blocked or budget.attempts >= args.limit:
                break
            capture = old['capture']
            recovery = {'case_id': old['case_id'], 'status': 'recovery_started', 'original_attempt_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'dataset_sha256': frozen_dataset_hash,
                'original_error_kind': old.get('error_kind'), 'new_retrieval_requests': 0,
                'capture_reused': True, 'created_at': datetime.now(timezone.utc).isoformat()}
            output = folder/'retries'/(old['case_id']+'_'+uuid4().hex[:8]+'.json')
            def save():
                output.write_text(json.dumps(recovery, ensure_ascii=False, indent=2), encoding='utf-8')
            save()
            def rank(query, pool):
                try:
                    delay = budget.reserve(now=time.monotonic())
                except RuntimeError as error:
                    return {'error_kind': str(error), 'ranked_chunks': None}
                if delay:
                    print('Pacing recovery', round(delay, 1), 'seconds', flush=True)
                    time.sleep(delay)
                result = collect_rerank(client, settings, query, pool)
                budget.observe(result.get('http_status'))
                if result.get('error_kind') is not None:
                    result.pop('raw_response', None)
                    result.pop('raw_response_text', None)
                return result
            policy = rank_with_facets(capture['query'], capture['original_chunks'], rank)
            if policy['ranked_chunks'] is None:
                recovery.update(status='recovery_failed', error_kind=policy['whole'].get('error_kind'), policy=policy)
            else:
                recovery.update(status='completed', record={'case_id': old['case_id'], 'question': capture['query'],
                    'original_chunks': capture['original_chunks'], 'chunk_top_k': capture['chunk_top_k'],
                    'tokenizer': capture['tokenizer'], 'budget': capture['budget'], 'policy': policy,
                    'retrieval_seconds': old.get('retrieval_seconds'),
                    'original_rerank_http_status': original_rerank_status(old),
                    'recovered_from_original_429': original_rerank_status(old) == 429})
            save()
            print(old['case_id'], recovery['status'], flush=True)
            if budget.blocked:
                print('Stopped immediately on provider 429; no more recovery requests.', flush=True)
                break
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
