"""Fixed, stratified generation sample; reuse identical contexts across B0/B1/B2/B3."""
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
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-cases', type=int, default=9, choices=range(1, 11))
    parser.add_argument('--max-calls', type=int, default=18, choices=range(1, 25))
    parser.add_argument('--case', action='append', default=[], help='Explicit predeclared supplemental sample IDs')
    args = parser.parse_args()
    if not args.execute:
        print('Preview: up to', args.max_cases, 'cases and', args.max_calls, 'unique model contexts, max_tokens=800; no calls.')
        return 0
    from app.context_builder import build_evidence_context
    from app.context_selection import select_context
    from app.answer_client import collect_answer
    from app.answer_config import load_answer_settings
    from app.answer_prompt import build_answer_messages
    from scripts.recover_upgrade_retrieval import verify_frozen_inputs
    verify_frozen_inputs()
    import httpx2 as httpx
    source = json.loads(args.source.read_text(encoding='utf-8'))
    selection = json.loads(args.selection.read_text(encoding='utf-8'))
    if selection['source_sha256'] != hashlib.sha256(args.source.read_bytes()).hexdigest():
        raise ValueError('Selection was not produced from this exact capture batch')
    dataset_file = ROOT/source['dataset_file']
    dataset = json.loads(dataset_file.read_text(encoding='utf-8'))
    assert hashlib.sha256(dataset_file.read_bytes()).hexdigest() == source['dataset_sha256']
    pools = {row['case_id']: row for row in source['records']}
    selections = {row['case_id']: row for row in selection['records']}
    available = [case for case in dataset['cases'] if case['id'] in pools and case['id'] in selections]
    if args.case:
        if len(set(args.case)) != len(args.case) or not set(args.case).issubset({case['id'] for case in available}):
            raise ValueError('Supplemental IDs must be distinct available test cases')
        available = [case for case in available if case['id'] in args.case]
    chosen, kinds = [], set()
    for case in available:
        if case['question_type'] not in kinds:
            chosen.append(case)
            kinds.add(case['question_type'])
    for case in available:
        if len(chosen) >= args.max_cases:
            break
        if case not in chosen:
            chosen.append(case)
    chosen = chosen[:args.max_cases]
    folder = ROOT/'evaluation/upgrade/generation'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8])
    folder.mkdir(parents=True)
    settings = load_answer_settings()
    calls, rows = 0, []
    report = {'kind': 'stratified_internal_test_generation', 'dataset_sha256': source['dataset_sha256'],
        'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
        'selection_sha256': hashlib.sha256(args.selection.read_bytes()).hexdigest(), 'model_alias': settings.answer_model,
        'protocol': {'max_chars': 30000, 'max_tokens': 800, 'thinking': 'disabled', 'sampling': 'explicit supplemental type coverage: '+','.join(args.case) if args.case else 'first available case per type in frozen dataset order, then fill by order',
            'reuse_identical_question_context': True, 'gold_answers_sent_to_model': False,
            'grading': {'answer_correctness': '0 incorrect / 1 partial / 2 correct', 'conditions': '0 major omission / 1 partial / 2 preserves relevant scope and exceptions',
                        'citation_support': 'check source support per policy claim; ID-format validity alone is insufficient',
                        'failure_stage': 'retrieval / context_organization / generation / provider / annotation'}},
        'sample_cases': [case['id'] for case in chosen], 'represented_types': sorted({c['question_type'] for c in chosen}),
        'total_test_cases': len(dataset['cases']), 'records': rows, 'generation_requests': 0,
        'limitations': ['Small stratified subset; cannot claim answer accuracy across the whole test set.',
            'This controlled generation experiment adds the same 30000-character whole-chunk budget to every variant.',
            'Identical question/context responses are reused, not independent stochastic replications.',
            'No LLM-as-Judge calls; qualitative grading is a separate source-grounded review.']}
    def save():
        report['generation_requests'] = calls
        (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with httpx.Client(timeout=httpx.Timeout(90, connect=5), trust_env=False, follow_redirects=False) as http:
        class Bounded:
            def post(self, url, **kwargs):
                kwargs['json']['max_tokens'] = 800
                return http.post(url, **kwargs)
        for case in chosen:
            cid = case['id']
            pool = {chunk['chunk_id']: chunk for chunk in pools[cid]['original_chunks']}
            cache = {}
            row = {'case_id': cid, 'question': case['question'], 'question_type': case['question_type'],
                'answerable': case['answerable'], 'variants': {}}
            rows.append(row)
            for variant in ('B0','B1','B2','B3'):
                ids = selections[cid]['variants'][variant]['selected_ids']
                chosen_chunks = select_context([{**pool[key], 'rerank_score': 1.0} for key in ids], max_chars=30000, min_score=0)['selected_chunks']
                if not chosen_chunks:
                    row['variants'][variant] = {'status': 'no_context', 'generation_performed': False}
                    continue
                bundle = build_evidence_context(chosen_chunks)
                messages = build_answer_messages(case['question'], bundle)
                context_hash = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                base = {'selected_ids': [c['chunk_id'] for c in chosen_chunks], 'context_sha256': context_hash}
                if context_hash in cache:
                    row['variants'][variant] = {**base, 'generation_performed': False, 'reused_from': cache[context_hash][0],
                                               'collection': cache[context_hash][1]}
                elif calls >= args.max_calls:
                    row['variants'][variant] = {**base, 'status': 'budget_not_executed', 'generation_performed': False}
                else:
                    calls += 1
                    collected = collect_answer(Bounded(), settings, case['question'], bundle)
                    if collected['error_kind'] is not None:
                        collected.pop('raw_response', None)
                        collected.pop('raw_response_text', None)
                    cache[context_hash] = (variant, collected)
                    row['variants'][variant] = {**base, 'generation_performed': True, 'collection': collected,
                                               'messages': messages}
                    if collected.get('http_status') == 429:
                        save()
                        print('Stopped on answer-provider 429; no automatic retry. Report:', folder/'report.json')
                        return 1
                save()
            print(cid, 'generated distinct contexts:', len(cache), flush=True)
    save()
    print('Generation requests:', calls, 'cases:', len(chosen))
    print('Report:', folder/'report.json')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
