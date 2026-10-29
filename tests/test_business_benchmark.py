def test_keyword_search_prefers_documents_containing_both_query_terms():
    from scripts.business_benchmark import keyword_rank
    chunks = {'a': {'content': 'Relocation probation relocation approval'},
              'b': {'content': 'Food travel expense approval'}, 'c': {'content': 'Approval only'}}
    assert keyword_rank(chunks, 'relocation probation')[0] == 'a'


def test_inspection_step_proxy_never_invents_a_completion():
    from scripts.business_benchmark import inspection_steps
    assert inspection_steps(['a', 'b'], [['a'], ['b']]) == 2
    assert inspection_steps(['a', 'c'], [['a'], ['b']]) is None
