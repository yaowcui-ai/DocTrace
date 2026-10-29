"""Simulated evidence-finding tasks; no human timing or enterprise validation claims."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TASKS = {'HR-M01': 'relocation probation uninterrupted passed',
         'HR-M03': 'promotion Workday internal mobility interview approval',
         'HR-M05': 'acting role bonus eligibility duration full time',
         'HR-M07': 'termination vested unvested options ninety days',
         'HR-M09': 'talent assessment three months performance potential',
         'HR-M15': 'offboarding Slack 1Password five days',
         'HR-M18': 'vested options termination Slack access ninety',
         'HR-M19': 'compensation base variable pay equity approval'}


def keyword_rank(chunks, query):
    tokens = set(re.findall(r'[a-z0-9]+', query.lower()))
    counts = {key: Counter(re.findall(r'[a-z0-9]+', value['content'].lower())) for key, value in chunks.items()}
    idf = {term: math.log(1+len(chunks)/(1+sum(term in row for row in counts.values()))) for term in tokens}
    scores = {key: sum(idf[term]*min(row[term], 3) for term in tokens) for key, row in counts.items()}
    return sorted(chunks, key=lambda key: (-scores[key], key))


def inspection_steps(ranking, groups):
    seen = set()
    for number, chunk in enumerate(ranking, 1):
        seen.add(chunk)
        if all(seen.intersection(group) for group in groups):
            return number
    return None


def main():
    from app.ablation_replay import gold_labels
    dataset_file = ROOT/'evaluation/hr_medium_dev_v2.json'
    dataset = {row['id']: row for row in json.loads(dataset_file.read_text(encoding='utf-8'))['cases']}
    chunks_file = ROOT/'runtime/gitlab_hr_v3/rag_storage/gitlab_hr_v3/kv_store_text_chunks.json'
    chunks = json.loads(chunks_file.read_text(encoding='utf-8'))
    replay = json.loads((ROOT/'evaluation/upgrade/reports/retrieval.json').read_text(encoding='utf-8'))
    b3 = {row['case_id']: row['variants']['B3']['selected_ids'] for row in replay['records']}
    rows = []
    for cid, query in TASKS.items():
        _, groups = gold_labels(dataset[cid], [{**row, 'chunk_id': key} for key, row in chunks.items()])
        started = time.perf_counter()
        keyword = keyword_rank(chunks, query)[:20]
        seconds = time.perf_counter()-started
        rows.append({'case_id': cid, 'question': dataset[cid]['question'], 'keyword_query': query,
            'keyword_search_cpu_seconds': seconds,
            'keyword': {'selected_ids': keyword, 'all_marked_conditions_found': all(set(g).intersection(keyword) for g in groups),
                'inspection_card_proxy': inspection_steps(keyword, groups)},
            'rag_saved_B3': {'selected_ids': b3[cid], 'all_marked_conditions_found': all(set(g).intersection(b3[cid]) for g in groups),
                'inspection_card_proxy': inspection_steps(b3[cid], groups)},
            'human_task_seconds': None, 'human_evidence_understanding': None})
    report = {'kind': 'simulated_business_scenario_evidence_diagnostic', 'created_at': datetime.now(timezone.utc).isoformat(),
        'participants': 0, 'provider_calls': 0, 'tasks': rows,
        'dataset_sha256': hashlib.sha256(dataset_file.read_bytes()).hexdigest(), 'chunk_store_sha256': hashlib.sha256(chunks_file.read_bytes()).hexdigest(),
        'summary': {'keyword_complete_tasks': sum(row['keyword']['all_marked_conditions_found'] for row in rows),
                    'rag_saved_complete_tasks': sum(row['rag_saved_B3']['all_marked_conditions_found'] for row in rows), 'task_count': len(rows)},
        'limitations': ['Reuses eight development scenarios and saved RAG rankings: diagnostic, not independent product validation.',
            'English keyword queries are manually supplied to an English corpus; this is an optimistic assisted keyword baseline.',
            'Inspection-card count is a proxy, not observed user actions, completion time, satisfaction, or comprehension.',
            'CPU keyword-search timing and historical saved RAG results are not comparable end-to-end latency measurements.',
            'Source facts are a frozen public policy snapshot, not actual employees or enterprise deployment.']}
    output = ROOT/'evaluation/upgrade/reports/business.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report['summary']))
    print('Report:', output)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
