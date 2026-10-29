"""Promote source-checked questions to a versioned INTERNAL test, without tuning on outputs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from scripts.build_upgrade_dataset import validate_cases, read_json, CORPUS, CHUNKS
    original = ROOT/'evaluation/upgrade_dataset/candidate-v1/candidate.json'
    source = read_json(original)
    cases = source['cases']
    fixes = {
        'HR-U002': ('expected_answer', '长期不休假会让工作知识集中在一个人身上，增加单点依赖。'),
        'HR-U006': ('expected_answer', '应准备在假期开始后15个自然日内提供出生、亲属关系或收养证明。'),
        'HR-U022': ('expected_answer', '不能追溯处理，应在申请搬迁时使用未来日期。'),
        'HR-U037': ('question', '参加Hone公开工作坊、分享工作情境时，应遵循GitLab哪个信息分享框架？'),
        'HR-U051': ('expected_answer', '从上一份工作到GitLab BV的间隔最多为三个月。'),
        'HR-U078': ('expected_answer', '不必；不愿直接面对或行为未停止时，可向Chief People Officer报告。'),
        'HR-U082': ('expected_answer', '不是强制分布，而是预期的分布基线。'),
        'HR-U094': ('expected_answer', '不容忍因提出骚扰投诉而遭到报复；可联系Chief People Officer。'),
        'HR-U098': ('expected_answer', '要求在最后一次live session结束后一个月内完成课程及缺课补学。'),
    }
    for case in cases:
        if case['id'] in fixes:
            field, value = fixes[case['id']]
            case[field] = value
        if case['id'] == 'HR-U037':
            case['expected_answer'] = '应遵循GitLab SAFE框架。'
    manifest = read_json(ROOT/CORPUS/'processing_manifest.json')
    old_cases = [row for path in (ROOT/'evaluation').glob('hr_*.json') for row in read_json(path).get('cases', [])]
    checks = validate_cases(cases, root=ROOT, manifest=manifest, chunks=read_json(ROOT/CHUNKS), old_cases=old_cases)
    # U025 was used by the three generation-security probes and managed smoke.
    # Exclude it rather than recycling an observed answer into the unseen test.
    promoted = []
    for case in cases:
        if case['id'] == 'HR-U025':
            continue
        item = {key: value for key, value in case.items() if key not in ('human_review_status', 'annotation_source')}
        item.update(split='test', quality_status='source_and_question_answer_constraints_checked')
        item['evidence_groups'] = [{'group_id': item['id']+'-E'+str(index), 'alternatives': [{
            'file_path': Path(evidence['path']).name, 'quote': evidence['quote']}]} for index, evidence in enumerate(item['evidence'], 1)]
        promoted.append(item)
    algorithm_files = ['app/facet_policy.py', 'app/prelimit_adapter.py', 'app/answer_prompt.py', 'app/context_builder.py',
                       'app/qa_pipeline.py', 'app/retrieval_client.py', 'app/rerank.py']
    frozen_code = {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in algorithm_files}
    dataset = {'dataset_id': 'hr_upgrade_internal_test_v1', 'corpus_id': 'gitlab_hr_v3',
        'split': 'test', 'external_blind_test': False, 'cases': promoted,
        'source_version': hashlib.sha256((ROOT/CORPUS/'processing_manifest.json').read_bytes()).hexdigest(),
        'protocol': {'development': 'evaluation/hr_medium_dev_v2.json', 'validation': 'evaluation/hr_medium_holdout_v1.json',
            'test_must_not_be_used_for_parameter_or_prompt_selection': True,
            'review': 'Exact source hash/quote/chunk checks for every item; question-answer constraint review; nine overextended draft expectations narrowed.',
            'excluded_observed_question_ids': ['HR-U025'], 'code_sha256_before_outputs': frozen_code,
            'original_candidate_sha256': hashlib.sha256(original.read_bytes()).hexdigest()},
        'limitations': ['Internal curated questions on the same public corpus, not an external blinded benchmark.',
            'Gold annotations cover explicit required evidence, not exhaustive relevance judgements for every retrieved chunk.',
            'Permission questions test refusal on public policies; real authorization is tested separately at the API boundary.',
            'After any tuning based on these results, this set must become regression and a new test set must be authored.']}
    output = ROOT/'evaluation/upgrade_dataset/internal-test-v1'
    output.mkdir(exist_ok=False)
    raw = (json.dumps(dataset, ensure_ascii=False, indent=2)+'\n').encode()
    (output/'dataset.json').write_bytes(raw)
    (output/'freeze.json').write_text(json.dumps({'dataset_sha256': hashlib.sha256(raw).hexdigest(),
        'case_count': len(promoted), 'source_checks': checks, 'code_sha256': frozen_code,
        'changes_from_draft': fixes, 'excluded_observed_cases': ['HR-U025']}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Frozen internal test questions:', len(promoted), 'external blind test: false')
    print('Dataset:', output/'dataset.json')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
