"""Source-grounded review of the saved nine-case sample; no extra model calls."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT/'evaluation/upgrade/generation/20261028T123140Z_53477acb/report.json'
    data = json.loads(source.read_text(encoding='utf-8'))
    # Ratings follow the saved input/output comparison; do not infer them from coverage.
    ratings = {
        'HR-U001': (2, 2, '双方正确区分日常time off与事件性较长leave。'),
        'HR-U002': (2, 2, '双方依据休假理念说明知识集中、文档化与交接；未给虚构量化收益。'),
        'HR-U003': (0, 2, 'B0在最终字符预算上下文缺少30天规则，保守拒答；B3给出30天与Compass路径。'),
        'HR-U004': (0, 2, 'B0缺少经理48小时和逐级升级依据而拒答；B3保留二者。'),
        'HR-U005': (1, 1, 'B0未取到全球公司规则而以地区说明作部分回答；B3找到born-or-newly-adopted条件，但据出生时间直接断言无资格，未保留任职后收养的可能。'),
        'HR-U028': (2, 2, '双方未提供他人工时，说明公开政策不含个人记录和受限分享规则。'),
        'HR-U006': (2, 2, '双方给出开始休假后15个自然日并保留准备提供的措辞。'),
        'HR-U007': (2, 2, '双方给出全球福利例外和实体/PEO额外福利范围。'),
        'HR-U008': (1, 2, 'B0用coaching及Parentaly局部安排解释一般规则，范围表达混杂；B3给出一般本人支付及账单模式例外。'),
    }
    reviews = []
    for case in data['records']:
        b0, b3, rationale = ratings[case['case_id']]
        row = {'case_id': case['case_id'], 'rationale': rationale, 'variants': {}}
        for variant in ('B0', 'B1', 'B2', 'B3'):
            collection = case['variants'][variant].get('collection', {})
            result = collection.get('result')
            if result is None:
                row['variants'][variant] = {'status': 'provider_or_budget_failure', 'score': None}
                continue
            ids = set(re.findall(r'\[(\d+)\]', result['response']))
            available = {r['reference_id'] for r in result['references']}
            score = b0 if variant == 'B0' else b3
            row['variants'][variant] = {'status': 'reviewed', 'answer_correctness_0_to_2': score,
                'citation_ids_exist': ids.issubset(available),
                'citation_semantics': 'core claim source-checked; not an exhaustive all-sentence precision score',
                'failure_stage': ('context_organization' if variant == 'B0' and case['case_id'] in {'HR-U003','HR-U004'} else
                                  'generation_condition_scope' if case['case_id'] == 'HR-U005' and variant != 'B0' else
                                  'partial_answer_or_scope' if score == 1 else None)}
        if case['case_id'] == 'HR-U003':
            row['extra_claim_flag'] = 'B3的“并非所有申请获批”可能混淆PTO审批与记录更正范围；不计作主结论错误，但需限制无关扩展。'
        reviews.append(row)
    summary = {}
    for variant in ('B0','B1','B2','B3'):
        scores = [row['variants'][variant].get('answer_correctness_0_to_2') for row in reviews]
        summary[variant] = {'fully_correct_main_answers': scores.count(2), 'partial': scores.count(1),
            'not_answered_correctly': scores.count(0), 'reviewed_cases': len(scores),
            'citation_id_structure_passes': sum(row['variants'][variant].get('citation_ids_exist') is True for row in reviews)}
    output = source.parent/'source_review.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'method': 'frozen rubric and source/output comparison',
            'external_blind_review': False, 'new_model_calls': 0, 'summary': summary, 'records': reviews,
            'limitations': ['Nine cases from the then-scorable subset; not full112-case answer accuracy.',
                'B1/B2/B3 reuse identical context answers; do not count their copies as independent generation trials.',
                'Citation ID validity is not semantic citation precision; no exhaustive per-claim precision number reported.',
                'No prompt/parameter updates were made from these test outcomes.']}, stream, ensure_ascii=False, indent=2)
    print(json.dumps(summary))
    print('Review:', output)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
