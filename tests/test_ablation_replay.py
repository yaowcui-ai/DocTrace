import pytest


def test_cached_native_adapter_uses_original_candidate_indexes():
    from app.ablation_replay import native_scores
    pool = [{'chunk_id': 'a', 'content': 'A'}, {'chunk_id': 'b', 'content': 'B'}]
    order = [{**pool[1], 'rerank_score': .8}, {**pool[0], 'rerank_score': .2}]
    assert native_scores(pool, order) == [{'index': 1, 'relevance_score': .8}, {'index': 0, 'relevance_score': .2}]


def test_cached_native_adapter_refuses_changed_or_missing_candidate():
    from app.ablation_replay import native_scores
    with pytest.raises(ValueError):
        native_scores([{'chunk_id': 'a', 'content': 'A'}], [{'chunk_id': 'a', 'content': 'Changed', 'rerank_score': .8}])


def test_known_quotes_map_to_gold_groups_without_marking_others_irrelevant():
    from app.ablation_replay import gold_labels
    case = {'evidence_groups': [{'alternatives': [{'file_path': 'a.md', 'quote': 'required approval'}]}]}
    chunks = [{'chunk_id': 'a', 'file_path': 'a.md', 'content': 'Prior required approval.'},
              {'chunk_id': 'b', 'file_path': 'b.md', 'content': 'unknown relevance'}]
    labels, groups = gold_labels(case, chunks)
    assert labels == {'a': 2} and groups == [['a']]


def test_annotated_gold_outside_candidate_pool_still_counts_as_a_recall_miss():
    from app.ablation_replay import gold_labels
    from app.benchmark import ranking_metrics
    case = {'evidence_ids': ['missing'], 'evidence_groups': [{'alternatives': [{'file_path': 'gold.md', 'quote': 'must approve'}]}]}
    labels, groups = gold_labels(case, [{'chunk_id': 'noise', 'file_path': 'other.md', 'content': 'No direct evidence'}])
    measured = ranking_metrics(['noise'], labels, groups, k=10)
    assert measured['recall'] == 0 and measured['evidence_group_coverage'] == 0
