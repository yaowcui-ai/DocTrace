"""Reuse saved whole-query rankings; cache every additional provider call."""
import argparse, hashlib, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import httpx2 as httpx
from app.facet_policy import rank_with_facets, plan_subqueries
from app.rerank_client import collect_rerank
from app.rerank_config import load_rerank_settings

def safe_error_record(collection):
    if collection.get('http_status') == 200:
        return collection
    result={**collection,'raw_response':None}
    result.pop('raw_response_text',None)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--execute', action='store_true', help='Allow uncached provider requests')
    parser.add_argument('--retry-failed-cache', action='store_true')
    args = parser.parse_args()
    read = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    plan = read(args.plan)
    assert sha(PROJECT/plan['dataset_file']) == plan['dataset_sha256']
    assert sha(PROJECT/plan['baseline_file']) == plan['baseline_sha256']
    baseline = read(PROJECT / plan['baseline_file'])
    records = {r['case_id']: r for r in baseline['records']}
    events = [json.loads(l) for l in args.journal.read_text(encoding='utf-8').splitlines()]
    whole = {}
    for event in events:
        if event['event']=='report_saved':
            assert sha(event['report_file']) == event['report_sha256']
            whole[event['case_id']] = read(event['report_file'])
    jobs = []
    for entry in plan['entries']:
        cid = entry['case_id']; snapshot = read(PROJECT / entry['snapshot_file'])
        assert sha(PROJECT / entry['snapshot_file']) == entry['snapshot_sha256']
        assert whole[cid]['candidate_snapshot_sha256'] == entry['snapshot_sha256']
        assert whole[cid]['collection']['error_kind'] is None
        query = records[cid]['question']; subs = plan_subqueries(query)
        print(cid, 'extra queries:', len(subs), flush=True)
        jobs.append((entry, snapshot, query))
    if args.dry_run or not args.execute: return
    settings = load_rerank_settings()
    cache = PROJECT / 'runtime/diagnostics/hr_autonomy/rerank_cache'; cache.mkdir(exist_ok=True)
    counts = {'provider_calls': 0, 'cache_hits': 0, 'whole_query_rankings_reused': len(jobs)}
    output = PROJECT / 'evaluation/runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8]+'_facet_batch.json')
    report = {'evaluation_kind': 'fixed_candidates_facet_policy', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'dataset_file': plan['dataset_file'], 'dataset_sha256': plan['dataset_sha256'],
              'baseline_file': plan['baseline_file'], 'baseline_sha256': plan['baseline_sha256'],
              'policy_source_sha256': sha(PROJECT/'app/facet_policy.py'), 'counts': counts, 'records': [], 'status': 'running'}
    def save(): output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0, write=30.0, pool=5.0), trust_env=False) as client:
        for entry, snapshot, query in jobs:
            cid = entry['case_id']
            def rank(subquery, chunks):
                key = hashlib.sha256(json.dumps({'url':settings.rerank_url,'model':settings.rerank_model,
                                                'query':subquery,'snapshot':entry['snapshot_sha256']},sort_keys=True).encode()).hexdigest()
                path = cache/(key+'.json')
                if path.exists():
                    cached = read(path)
                    if cached['collection']['error_kind'] is None or not args.retry_failed_cache:
                        counts['cache_hits'] += 1
                        return safe_error_record(cached['collection'])
                    backup = cache/(key+'_failed_'+uuid4().hex+'.json')
                    assert path.resolve().is_relative_to(cache.resolve()) and backup.resolve().is_relative_to(cache.resolve())
                    path.rename(backup)
                counts['provider_calls'] += 1
                print('CALL',cid,subquery,flush=True)
                collection = collect_rerank(client,settings,subquery,chunks)
                # Error bodies may echo authorization headers. Keep status/timing, not bodies.
                collection = safe_error_record(collection)
                event = {'created_at_utc':datetime.now(timezone.utc).isoformat(),'query':subquery,
                         'snapshot_sha256':entry['snapshot_sha256'],'model':settings.rerank_model,
                         'provider_url':settings.rerank_url,'collection':collection}
                with path.open('x',encoding='utf-8') as f:json.dump(event,f,ensure_ascii=False,indent=2)
                return collection
            result = rank_with_facets(query,snapshot['merged_chunks'],rank,whole=whole[cid]['collection'])
            report['records'].append({'case_id':cid,'question':query,'snapshot_file':entry['snapshot_file'],
                                      'snapshot_sha256':entry['snapshot_sha256'],'budget':snapshot['budget'],
                                      'chunk_top_k':snapshot['chunk_top_k'],'tokenizer':snapshot['tokenizer_model_name'],
                                      'original_chunks':snapshot['merged_chunks'],'policy':result})
            save()
            print('DONE',cid,result['strategy'],flush=True)
    report['status']='completed';save();print('Report:',output,flush=True)


if __name__=='__main__':main()
