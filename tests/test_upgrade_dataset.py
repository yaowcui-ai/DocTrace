import copy
import hashlib
import json

import pytest


@pytest.fixture
def sample(tmp_path):
    source = tmp_path / 'data/gitlab_hr/v3/cleaned/policy.md'
    source.parent.mkdir(parents=True)
    source.write_text('Policy\nThe annual cap is 300 USD.\n', encoding='utf-8')
    manifest = {'corpus_id': 'gitlab_hr_v3', 'documents': [{'document_id': 'policy',
        'cleaned_file': 'cleaned/policy.md', 'cleaned_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'source_url': 'https://example.org/policy'}]}
    case = {'id': 'NEW-001', 'question': '年度额度上限是多少？', 'expected_answer': '年度上限为300美元。',
        'question_type': 'simple_fact', 'answerable': True, 'difficulty': 'easy',
        'source_cluster': 'benefits', 'split': 'validation_candidate',
        'annotation_source': 'assistant_authored_source_verified', 'human_review_status': 'pending',
        'source_version': 'gitlab_hr_v3', 'evidence_ids': ['chunk-1'],
        'evidence': [{'path': 'data/gitlab_hr/v3/cleaned/policy.md', 'quote': 'The annual cap is 300 USD.',
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'source_url': 'https://example.org/policy'}]}
    return tmp_path, manifest, case, {'chunk-1': {'file_path': 'policy.md', 'content': 'The annual cap is 300 USD.'}}


def validate(sample, cases=None, old=None):
    from scripts.build_upgrade_dataset import validate_cases
    root, manifest, case, chunks = sample
    return validate_cases(cases or [case], root=root, manifest=manifest, chunks=chunks, old_cases=old or [])


def test_source_grounded_case_passes_and_remains_pending(sample):
    report = validate(sample)
    assert report['case_count'] == 1
    assert report['independent_external_test'] is False
    assert report['human_review_pending'] == 1


@pytest.mark.parametrize('mutation', ['quote', 'hash', 'path', 'id', 'human', 'empty', 'url'])
def test_invalid_evidence_and_annotation_are_rejected(sample, mutation):
    _, _, case, _ = sample
    if mutation == 'quote': case['evidence'][0]['quote'] = 'Invented cap 500 USD'
    elif mutation == 'hash': case['evidence'][0]['sha256'] = '0' * 64
    elif mutation == 'path': case['evidence'][0]['path'] = '../outside.md'
    elif mutation == 'id': case['evidence_ids'] = ['invented-chunk']
    elif mutation == 'human': case['human_review_status'] = 'verified'
    elif mutation == 'empty': case['expected_answer'] = ''
    elif mutation == 'url': case['evidence'][0]['source_url'] = 'https://wrong.example/'
    with pytest.raises(ValueError):
        validate(sample)


def test_duplicate_old_question_or_quote_is_rejected(sample):
    case = sample[2]
    for old in [{'question': case['question']}, {'question': 'old', 'evidence': [{'quote': case['evidence'][0]['quote']}]}]:
        with pytest.raises(ValueError):
            validate(sample, old=[old])


def test_quotes_in_old_nested_evidence_groups_are_also_excluded(sample):
    old = {'question': 'old question', 'evidence_groups': [{'alternatives': [
        {'quote': sample[2]['evidence'][0]['quote']}]}]}
    with pytest.raises(ValueError):
        validate(sample, old=[old])


def test_source_cannot_cross_splits_or_clusters(sample):
    second = copy.deepcopy(sample[2])
    second.update(id='NEW-002', question='另一个不同条件的问题？', split='development_candidate')
    with pytest.raises(ValueError):
        validate(sample, cases=[sample[2], second])


def test_freeze_output_is_immutable(sample, tmp_path):
    from scripts.build_upgrade_dataset import write_bundle
    output = tmp_path / 'bundle'
    dataset = {'cases': [sample[2]]}
    write_bundle(output, dataset, {'case_count': 1})
    before = (output / 'candidate.json').read_bytes()
    with pytest.raises(FileExistsError):
        write_bundle(output, {'cases': []}, {})
    assert (output / 'candidate.json').read_bytes() == before
