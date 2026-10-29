"""Offline validation and immutable packaging of assistant-authored evaluation cases.

No question or answer generation, provider calls, retrieval or application imports.
The authored rows are reviewed text, not a template that invents questions.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
CORPUS = Path('data/gitlab_hr/v3')
CHUNKS = Path('runtime/gitlab_hr_v3/rag_storage/gitlab_hr_v3/kv_store_text_chunks.json')
TYPES = {'simple_fact', 'conditions', 'exceptions', 'multi_document_comparison',
    'missing_region_clarification', 'no_answer_personal_records', 'confusable_policies',
    'composite', 'permission_restricted'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold()


def all_quotes(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'quote' and isinstance(item, str):
                yield item
            else:
                yield from all_quotes(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_quotes(item)


def validate_cases(cases, *, root, manifest, chunks, old_cases):
    selected = {str((CORPUS / d['cleaned_file']).as_posix()): d for d in manifest['documents']}
    old_questions = {normalized(c.get('question', '')) for c in old_cases}
    old_quotes = set(all_quotes(old_cases))
    seen_ids, seen_questions, groups, sources = set(), set(), {}, set()
    errors = []
    for case in cases:
        cid = case.get('id', '?')
        def fail(message): errors.append(f'{cid}: {message}')
        for key in ['id', 'question', 'expected_answer', 'question_type', 'source_cluster', 'split', 'source_version']:
            if not isinstance(case.get(key), str) or not case[key].strip(): fail('missing ' + key)
        if case.get('id') in seen_ids: fail('duplicate id')
        seen_ids.add(case.get('id'))
        question = normalized(case.get('question', ''))
        if question in seen_questions or question in old_questions: fail('duplicate question or old regression question')
        seen_questions.add(question)
        if case.get('question_type') not in TYPES: fail('invalid question type')
        if type(case.get('answerable')) is not bool: fail('answerable must be boolean')
        if case.get('difficulty') not in {'easy', 'medium', 'hard'}: fail('invalid difficulty')
        if case.get('split') not in {'development_candidate', 'validation_candidate'}: fail('invalid candidate split')
        if case.get('source_version') != manifest['corpus_id']: fail('wrong source version')
        if case.get('annotation_source') != 'assistant_authored_source_verified' or case.get('human_review_status') != 'pending':
            fail('candidate annotations must remain assistant-authored and human-review pending')
        evidence, evidence_ids = case.get('evidence'), case.get('evidence_ids')
        if not isinstance(evidence, list) or not evidence: fail('evidence is required'); continue
        if not isinstance(evidence_ids, list) or not evidence_ids or any(i not in chunks for i in evidence_ids):
            fail('unknown or missing evidence id'); continue
        case_paths = set()
        for e in evidence:
            path, quote = e.get('path'), e.get('quote')
            doc = selected.get(path)
            if doc is None: fail('source outside selected manifest'); continue
            target = (root / path).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file(): fail('invalid source path'); continue
            data = target.read_bytes()
            if sha(data) != doc['cleaned_sha256'] or e.get('sha256') != doc['cleaned_sha256']: fail('source hash mismatch')
            if e.get('source_url') != doc['source_url']: fail('source URL mismatch')
            if not isinstance(quote, str) or not quote.strip() or quote not in data.decode('utf-8'): fail('quote not exact source text'); continue
            if quote in old_quotes: fail('exact old evidence quote reused')
            matching = [i for i in evidence_ids if quote in chunks[i].get('content', '')
                and Path(chunks[i].get('file_path', '').replace('\\', '/')).name == target.name]
            if not matching: fail('quote not located in declared source chunk')
            for i in evidence_ids:
                if not any(ev.get('quote', '') in chunks[i].get('content', '')
                    and Path(chunks[i].get('file_path', '').replace('\\', '/')).name == Path(ev.get('path', '')).name for ev in evidence):
                    fail('unrelated evidence chunk')
            group = (case.get('source_cluster'), case.get('split'))
            if path in groups and groups[path] != group: fail('source crosses cluster/split boundary')
            groups[path] = group
            sources.add(path)
            case_paths.add(path)
        if case.get('question_type') == 'multi_document_comparison' and len(case_paths) < 2:
            fail('multi-document type requires distinct policies')
    # One policy cluster must remain wholly in one split, even across documents.
    cluster_splits = {}
    for case in cases:
        cluster_splits.setdefault(case.get('source_cluster'), set()).add(case.get('split'))
    if any(len(s) > 1 for s in cluster_splits.values()): errors.append('policy cluster crosses splits')
    if errors: raise ValueError('\n'.join(errors))
    return {'case_count': len(cases), 'source_document_count': len(sources), 'selected_document_count': len(selected),
        'question_types': dict(sorted(Counter(c['question_type'] for c in cases).items())),
        'splits': dict(sorted(Counter(c['split'] for c in cases).items())),
        'source_clusters': dict(sorted(Counter(c['source_cluster'] for c in cases).items())),
        'human_review_pending': len(cases), 'independent_external_test': False,
        'quote_exact_match': True, 'source_hashes_verified': True, 'chunk_ids_verified': True,
        'old_question_and_exact_quote_overlap': 0, 'provider_calls': 0,
        'missing_sources': sorted(set(selected) - sources)}


def materialize(rows, *, root, manifest, chunks, assignments):
    docs = {d['document_id']: d for d in manifest['documents']}
    cases = []
    for number, row in enumerate(rows, 1):
        source, question, answer, kind, authored_evidence = row
        pairs = authored_evidence if isinstance(authored_evidence, list) else [[source, authored_evidence]]
        clusters = {assignments['documents'][doc_id] for doc_id, _ in pairs}
        if len(clusters) != 1: raise ValueError(f'Cross-cluster evidence must be assigned together before freezing: {number}')
        cluster = clusters.pop()
        evidence, ids = [], set()
        for doc_id, quote in pairs:
            doc = docs[doc_id]
            path = (CORPUS / doc['cleaned_file']).as_posix()
            evidence.append({'path': path, 'quote': quote, 'sha256': doc['cleaned_sha256'], 'source_url': doc['source_url']})
            ids.update(k for k, v in chunks.items() if quote in v.get('content', '')
                and Path(v.get('file_path', '').replace('\\', '/')).name == Path(path).name)
        cases.append({'id': f'HR-U{number:03d}', 'question': question, 'expected_answer': answer,
            'evidence_ids': sorted(ids), 'evidence': evidence, 'question_type': kind,
            'answerable': kind not in {'no_answer_personal_records', 'permission_restricted', 'missing_region_clarification'},
            'difficulty': 'easy' if kind == 'simple_fact' else 'hard' if kind in {'multi_document_comparison', 'composite'} else 'medium',
            'source_version': manifest['corpus_id'], 'source_cluster': cluster,
            'split': assignments['splits'][cluster], 'annotation_source': 'assistant_authored_source_verified',
            'human_review_status': 'pending'})
    return cases


def write_bundle(output, dataset, report):
    # mkdir(exist_ok=False) prevents modifying an existing freeze, even partly.
    output.mkdir(parents=True, exist_ok=False)
    encoded = (json.dumps(dataset, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (output / 'candidate.json').write_bytes(encoded)
    (output / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    freeze = {'status': 'draft_pending_human_review', 'candidate_sha256': sha(encoded),
        'candidate_bytes': len(encoded), 'case_count': len(dataset['cases']),
        'independent_external_test': False, 'human_review_status': 'pending',
        'promotion_gate': 'Independent human source review and protocol sign-off are required before final freeze or test claims.'}
    (output / 'freeze-draft.json').write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    directory = ROOT / 'evaluation/upgrade_dataset'
    manifest = read_json(ROOT / CORPUS / 'processing_manifest.json')
    chunks = read_json(ROOT / CHUNKS)
    rows = read_json(directory / 'authoring_rows.json')
    assignments = read_json(directory / 'policy_clusters.json')
    cases = materialize(rows, root=ROOT, manifest=manifest, chunks=chunks, assignments=assignments)
    old_files = sorted((ROOT / 'evaluation').glob('hr_*.json'))
    old_cases = [c for p in old_files for c in read_json(p).get('cases', [])]
    report = validate_cases(cases, root=ROOT, manifest=manifest, chunks=chunks, old_cases=old_cases)
    report['regression_files'] = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in old_files}
    report['curation_sha256'] = sha((directory / 'authoring_rows.json').read_bytes())
    report['policy_assignment_sha256'] = sha((directory / 'policy_clusters.json').read_bytes())
    dataset = {'dataset_id': 'hr_upgrade_candidate_v1', 'corpus_id': manifest['corpus_id'],
        'status': 'draft_pending_human_review', 'annotation_source': 'assistant_authored_source_verified',
        'independent_external_test': False, 'source_license': 'CC-BY-SA-4.0',
        'source_manifest_sha256': sha((ROOT / CORPUS / 'processing_manifest.json').read_bytes()),
        'limitations': ['Assistant authored and assistant source-checked; independent human review pending.',
            'Same public frozen corpus as regression sets; not an external blinded test.',
            'Questions and expectations were authored without retrieval, model outcomes or tuning.',
            'Policies describe this snapshot; current legal/benefit eligibility is not established.'], 'cases': cases}
    if args.output: write_bundle(args.output, dataset, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
