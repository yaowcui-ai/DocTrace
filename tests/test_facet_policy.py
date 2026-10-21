import copy
import pytest
from app.facet_policy import plan_subqueries, interleave_rankings, rank_with_facets


def chunk(cid):
    return {'chunk_id': cid, 'file_path': cid+'.md', 'content': 'policy '+cid}


def result(ids):
    return {'error_kind': None, 'http_status': 200, 'ranked_chunks': [chunk(i) for i in ids]}


def test_enumeration_is_split_without_inventing_answer_terms():
    q = '基本工资、variable pay目标金额、股权授予都属于已保证的报酬吗？根据页面分别解释。'
    assert plan_subqueries(q) == ['基本工资属于已保证的报酬吗？', 'variable pay目标金额属于已保证的报酬吗？', '股权授予属于已保证的报酬吗？']


def test_explicit_combined_questions_preserve_the_original_clauses():
    q = '导师目标如何记录？IGP多久更新？请结合两类指引回答。'
    assert plan_subqueries(q) == ['导师目标如何记录？', 'IGP多久更新？']
    assert plan_subqueries('年假多少天？需要谁批准？') == []
    assert plan_subqueries('A、B、C、D都需要审批吗？') == []


def test_interleave_deduplicates_without_mutating_inputs():
    ranks = [result('ABCD')['ranked_chunks'], result('CADB')['ranked_chunks']]
    before = copy.deepcopy(ranks)
    assert [c['chunk_id'] for c in interleave_rankings(ranks)] == list('ACBD')
    assert ranks == before


def test_interleave_rejects_changed_content_and_incomplete_branches():
    base = result('AB')['ranked_chunks']
    changed = copy.deepcopy(base); changed[0]['content'] = 'corrupted'
    with pytest.raises(ValueError): interleave_rankings([base, changed])
    with pytest.raises(ValueError): interleave_rankings([base, base[:1]])


def test_simple_query_reuses_whole_result_without_extra_provider_calls():
    def forbidden(q, cs): pytest.fail('No extra calls for simple question')
    r = rank_with_facets('年假多少天？', [chunk('A'), chunk('B')], forbidden, whole=result('BA'))
    assert r['strategy'] == 'whole_query_rerank'
    assert [c['chunk_id'] for c in r['ranked_chunks']] == list('BA')


def test_facets_retain_whole_query_anchor_and_distinct_evidence():
    calls = []
    def provider(q, cs):
        calls.append(q)
        return result('CBA') if len(calls)==1 else result('BCA')
    r = rank_with_facets('甲如何处理？乙多久更新？请结合说明。',
                         [chunk(i) for i in 'ABC'], provider, whole=result('ABC'))
    assert len(calls) == 2
    assert r['strategy'] == 'facet_interleave_v1'
    assert [c['chunk_id'] for c in r['ranked_chunks']] == list('ACB')


def test_branch_failure_falls_back_explicitly_not_as_empty_evidence():
    def failed(q, cs): return {'error_kind': 'timeout', 'ranked_chunks': None}
    r = rank_with_facets('甲如何处理？乙多久更新？请结合说明。',
                         [chunk(i) for i in 'ABC'], failed, whole=result('ABC'))
    assert r['strategy'] == 'fallback_whole_query'
    assert r['fallback_reason'] == 'facet_request_failed'
    assert len(r['ranked_chunks']) == 3
