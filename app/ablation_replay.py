"""Offline B0/B1/B2/B3 replay on historical captures, including native LightRAG rerank.

No provider requests. This is NOT an independent new test set or a cold latency test.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess

from .benchmark import ranking_metrics, strict_gold_proxy

ROOT = Path(__file__).resolve().parents[1]


def native_scores(original, ranked):
    by_id = {item['chunk_id']: (index, item) for index, item in enumerate(original)}
    if len(by_id) != len(original) or len(ranked) != len(original):
        raise ValueError('Complete unique candidate pool is required')
    result, seen = [], set()
    for item in ranked:
        index, before = by_id[item['chunk_id']]
        score = item.get('rerank_score')
        if index in seen or before['content'] != item['content'] or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError('Changed content, duplicate identity, or invalid score')
        seen.add(index)
        result.append({'index': index, 'relevance_score': score})
    return result


def gold_labels(case, chunks):
    # Keep annotated positives outside the recalled pool: their absence is a miss,
    # not a reason to remove them from the recall denominator.
    labels, groups = {key: 2 for key in case.get('evidence_ids', [])}, []
    for group in case['evidence_groups']:
        matched = []
        for chunk in chunks:
            if any(chunk['file_path'] == alternative['file_path'] and alternative['quote'] in chunk['content']
                   for alternative in group['alternatives']):
                matched.append(chunk['chunk_id'])
                labels[chunk['chunk_id']] = 2
        groups.append(matched)
    return labels, groups


PROGRAM = r'''
import asyncio, json, socket, sys, time
def blocked(*args,**kwargs): raise RuntimeError('Network forbidden in offline ablation')
socket.socket.connect=blocked
from lightrag import QueryParam
from lightrag.utils import process_chunks_unified,TiktokenTokenizer,generate_reference_list_from_chunks,render_chunks_context_text
async def main():
    rows=json.load(sys.stdin); output=[]
    for row in rows:
        tokenizer=TiktokenTokenizer(row['tokenizer'])
        original=row['variants']['B0']
        async def reranker(query,documents,top_n=None):
            assert documents==[c['content'] for c in original]
            return row['scores'][:top_n] if top_n else row['scores']
        result={'case_id':row['case_id'],'variants':{}}
        for name in ['B0','B1','B2','B3']:
            chunks=original if name=='B1' else row['variants'][name]
            config={'tokenizer':tokenizer,'rerank_model_func':reranker,'min_rerank_score':0.0}
            param=QueryParam(mode='mix',chunk_top_k=row['top_k'],enable_rerank=name=='B1')
            started=time.perf_counter()
            selected=await process_chunks_unified(row['query'],chunks,param,config,chunk_token_limit=row['budget'])
            _,rendered=generate_reference_list_from_chunks(selected)
            result['variants'][name]={'selected_ids':[c['chunk_id'] for c in selected],
                'rendered_chunk_tokens':len(tokenizer.encode(render_chunks_context_text(rendered))),
                'offline_selector_seconds':round(time.perf_counter()-started,6)}
        output.append(result)
    print(json.dumps(output))
asyncio.run(main())
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--host-snapshot', action='store_true', help='Execute hash-verified upstream definitions locally; no Docker required')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; preserve historical results and choose a new filename')
    source = json.loads(args.source.read_text(encoding='utf-8'))
    dataset_path = ROOT/source['dataset_file']
    if hashlib.sha256(dataset_path.read_bytes()).hexdigest() != source['dataset_sha256']:
        raise ValueError('Frozen dataset hash mismatch')
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    cases = {row['id']: row for row in dataset['cases']}
    internal_test = dataset.get('split') == 'test'
    reference = ROOT/'evaluation/diagnostics/20261016T044508Z_38dfaa7a_utils.py.txt'
    if args.host_snapshot:
        from .native_snapshot import EXPECTED_SHA256
        utils_hash = EXPECTED_SHA256
    else:
        utils_hash = subprocess.check_output(['docker', 'exec', 'doctrace-hr-v3-lightrag_hr_v3-1', 'sha256sum', '/app/lightrag/utils.py'], text=True).split()[0]
    if utils_hash != hashlib.sha256(reference.read_bytes()).hexdigest():
        raise ValueError('Pinned upstream selector source differs')
    inputs = []
    for row in source['records']:
        inputs.append({'case_id': row['case_id'], 'query': row['question'], 'tokenizer': row['tokenizer'],
            'top_k': row['chunk_top_k'], 'budget': row['budget']['available_chunk_tokens'],
            'scores': native_scores(row['original_chunks'], row['policy']['whole']['ranked_chunks']),
            'variants': {'B0': row['original_chunks'], 'B2': row['policy']['whole']['ranked_chunks'],
                         'B3': row['policy']['ranked_chunks']}})
    command = ['docker','exec','-i','doctrace-hr-v3-lightrag_hr_v3-1','/app/.venv/bin/python','-c',PROGRAM]
    if args.host_snapshot:
        import asyncio
        from .native_snapshot import replay_rows
        measurements = asyncio.run(replay_rows(inputs))
    else:
        run = subprocess.run(command, input=json.dumps(inputs), capture_output=True, text=True, encoding='utf-8', check=True)
        measurements = json.loads(run.stdout)
    output = []
    summary = {name: {'matched_groups': 0, 'expected_groups': 0, 'complete_cases': 0, 'tokens': 0} for name in ['B0','B1','B2','B3']}
    for row, measured in zip(source['records'], measurements, strict=True):
        assert row['case_id'] == measured['case_id']
        relevance, groups = gold_labels(cases[row['case_id']], row['original_chunks'])
        values = {}
        for name, selected in measured['variants'].items():
            ids = selected['selected_ids']
            hits = sum(bool(set(group).intersection(ids)) for group in groups)
            values[name] = {**selected, 'recall_at_5': ranking_metrics(ids, relevance, groups, k=5),
                           'recall_at_10': ranking_metrics(ids, relevance, groups, k=10),
                           'strict_gold_proxy_at_10': strict_gold_proxy(ids, [c['chunk_id'] for c in row['original_chunks']], list(relevance), k=10),
                           'matched_groups': hits, 'expected_groups': len(groups)}
            for key, count in [('matched_groups', hits), ('expected_groups', len(groups)),
                               ('complete_cases', int(hits == len(groups))), ('tokens', selected['rendered_chunk_tokens'])]:
                summary[name][key] += count
        output.append({'case_id': row['case_id'], 'variants': values,
                       'B1_equals_B2_ids': values['B1']['selected_ids'] == values['B2']['selected_ids']})
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
        'kind': 'frozen_internal_test_capture_ablation' if internal_test else 'historical_capture_offline_ablation',
        'dataset_id': dataset.get('dataset_id'), 'scorable_count': len(output),
        'requested_test_count': source.get('test_count', len(dataset['cases'])), 'unresolved_cases': source.get('failures', []),
        'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(), 'dataset_sha256': source['dataset_sha256'],
        'upstream_utils_sha256': utils_hash, 'provider_calls': 0, 'summary': summary, 'records': output,
        'selector_execution': 'hash_checked_upstream_definitions_sequential_host' if args.host_snapshot else 'pinned_container_native_functions',
        'protocol': {'mode': 'mix', 'total_token_budget': 40000, 'chunk_top_k': 20, 'min_rerank_score': 0,
            'B0': 'Pinned native selector, rerank disabled, saved original candidate ordering',
            'B1': 'Pinned native selector and native rerank adapter, saved provider scores replayed',
            'B2': 'Saved complete-pool custom whole-query ordering, native selection',
            'B3': 'Saved conditional composite fusion ordering, native selection'},
        'limitations': [('Internal test candidates were frozen before retrieval; not external blinded evaluation.' if internal_test
                          else 'Reuses historical development/validation cases: not a new independent benchmark.'),
            'Scorable cases exclude unresolved provider failures; all such failures are listed and this subset may be biased.',
            'Uses recorded provider scores, not new provider responses or paid cold latency.',
            'Unjudged chunks do not count as irrelevant; nDCG and noise ratio are null when labels are incomplete.',
            'The separately labeled strict-gold nDCG proxy treats non-gold as zero ONLY within that literal-evidence proxy; it is not exhaustive semantic relevance or true noise ratio.',
            'Recall denominator includes annotated-positive chunks only; cannot infer exhaustive relevance.',
            'B1/B2 may be equivalent: the pinned upstream already reranks before top-k/token truncation.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(summary))
    print('B1/B2 identical cases:', sum(item['B1_equals_B2_ids'] for item in output), '/', len(output))
    print('Report:', args.output)


if __name__ == '__main__':
    main()
