"""Budgeted new-test retrieval capture and rerank; starts with three cases, no retries."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int, default=3, choices=range(1, 113))
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--max-rerank-requests', type=int, default=12, choices=range(1, 225))
    parser.add_argument('--min-interval-seconds', type=int, default=30, choices=range(0, 121))
    args = parser.parse_args()
    if not args.execute:
        print('Preview only: fixed internal-test retrieval, limit', args.limit, 'max direct rerank requests', args.max_rerank_requests)
        return 0
    import httpx2 as httpx
    from app.rerank_client import collect_rerank
    from app.rerank_config import load_rerank_settings
    from app.facet_policy import rank_with_facets
    from app.config import load_settings
    from app.experiment_budget import ProviderBudget
    dataset_path = ROOT/'evaluation/upgrade_dataset/internal-test-v1/dataset.json'
    dataset_raw = dataset_path.read_bytes()
    dataset = json.loads(dataset_raw)
    freeze = json.loads((dataset_path.parent/'freeze.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(dataset_raw).hexdigest() == freeze['dataset_sha256']
    for path, expected in freeze['code_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected, 'Frozen code changed: '+path
    output = args.resume.resolve() if args.resume else ROOT/'evaluation/upgrade/new_retrieval'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    if args.resume and not output.is_relative_to((ROOT/'evaluation/upgrade/new_retrieval').resolve()):
        raise ValueError('Resume must refer to a project experiment directory')
    output.mkdir(parents=True, exist_ok=bool(args.resume))
    settings = load_settings()
    rerank_settings = load_rerank_settings()
    requests = 0
    budget = ProviderBudget(max_attempts=args.max_rerank_requests, min_interval=args.min_interval_seconds)
    records, failures = [], []
    with httpx.Client(timeout=httpx.Timeout(90, connect=5), trust_env=False, follow_redirects=False) as client:
        health = client.get('http://127.0.0.1:9632/health', headers={'X-API-Key': settings.lightrag_api_key})
        health.raise_for_status()
        assert health.json().get('webui_title') == 'DocTrace Evaluation Probe'
        for case in dataset['cases'][:args.limit]:
            if budget.blocked or requests >= args.max_rerank_requests:
                print('Stopped: provider rate limit or explicit request budget; unattempted cases remain unattempted.', flush=True)
                break
            path = output/(case['id']+'.json')
            if path.exists():
                saved = json.loads(path.read_text(encoding='utf-8'))
                if saved.get('status') == 'completed':
                    records.append(saved['record'])
                else:
                    failures.append({'case_id': case['id'], 'status': saved.get('status'), 'error_kind': saved.get('error_kind')})
                print(case['id'], 'reuse existing attempt:', saved.get('status'), flush=True)
                continue
            saved = {'case_id': case['id'], 'status': 'retrieval_submission_started', 'created_at': datetime.now(timezone.utc).isoformat()}
            def save():
                path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
            save()
            try:
                import time
                started = time.perf_counter()
                response = client.post('http://127.0.0.1:9632/query/data', headers={'X-API-Key': settings.lightrag_api_key},
                    json={'query': case['question'], 'mode': 'mix', 'enable_rerank': False,
                          'top_k': 40, 'chunk_top_k': 20, 'max_total_tokens': 40000})
                saved['retrieval_seconds'] = round(time.perf_counter()-started, 3)
                saved['retrieval_http_status'] = response.status_code
                response.raise_for_status()
                body = response.json()
                capture = body['metadata']['doctrace_probe']
                chunks = capture['original_chunks']
                assert capture['query'] == case['question'] and len(chunks) <= 200
                assert sum(len(c['content']) for c in chunks) <= 1_500_000
                saved.update(status='retrieval_captured', capture=capture)
                save()
                def rank(query, pool):
                    nonlocal requests
                    if requests >= args.max_rerank_requests:
                        return {'error_kind': 'budget_exceeded', 'ranked_chunks': None}
                    try:
                        delay = budget.reserve(now=time.monotonic())
                    except RuntimeError as error:
                        return {'error_kind': str(error), 'ranked_chunks': None}
                    if delay:
                        print('Pacing rerank request for', round(delay, 1), 'seconds', flush=True)
                        time.sleep(delay)
                    requests += 1
                    event = collect_rerank(client, rerank_settings, query, pool)
                    budget.observe(event.get('http_status'))
                    if event.get('error_kind') is not None:
                        event.pop('raw_response', None)
                        event.pop('raw_response_text', None)
                    return event
                policy = rank_with_facets(case['question'], chunks, rank)
                if policy['ranked_chunks'] is None:
                    saved.update(status='rerank_failed', error_kind=policy['whole'].get('error_kind'), policy=policy)
                    failures.append({'case_id': case['id'], 'status': saved['status'], 'error_kind': saved['error_kind']})
                else:
                    record = {'case_id': case['id'], 'question': case['question'], 'original_chunks': chunks,
                        'chunk_top_k': capture['chunk_top_k'], 'tokenizer': capture['tokenizer'],
                        'budget': capture['budget'], 'policy': policy, 'retrieval_seconds': saved['retrieval_seconds']}
                    saved.update(status='completed', record=record)
                    records.append(record)
                save()
                print(case['id'], saved['status'], 'candidates', len(chunks), 'retrieval_s', saved['retrieval_seconds'], flush=True)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AssertionError) as error:
                saved.update(status='failed_no_automatic_retry', error_kind=type(error).__name__)
                save()
                failures.append({'case_id': case['id'], 'status': saved['status'], 'error_kind': saved['error_kind']})
                print(case['id'], saved['status'], saved['error_kind'], flush=True)
    summary = {'dataset_file': dataset_path.relative_to(ROOT).as_posix(), 'dataset_sha256': freeze['dataset_sha256'],
        'status': 'completed_with_failures' if failures else 'completed', 'records': records, 'failures': failures,
        'requested_case_count': args.limit, 'total_test_cases': len(dataset['cases']), 'rerank_requests_this_invocation': requests,
        'note': 'One LightRAG request per newly attempted case; mix may internally call keyword generation and Embedding. Counts here are not supplier billing counts.',
        'generation_answer_requests': 0}
    target = output/('batch_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6]+'.json')
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Batch:', target)
    print('Successful:', len(records), 'failed:', len(failures), 'new rerank requests:', requests)
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
