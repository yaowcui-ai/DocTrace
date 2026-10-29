import math

import pytest


def test_ranked_metrics_match_hand_calculation():
    from app.benchmark import ranking_metrics
    result = ranking_metrics(['noise', 'b', 'a'], {'noise': 0, 'a': 2, 'b': 1}, [['a'], ['b']], k=10)
    assert result['recall'] == 1
    assert result['mrr'] == .5
    assert result['ndcg'] == pytest.approx((1/math.log2(3)+3/math.log2(4))/(3+1/math.log2(3)))
    assert result['evidence_group_coverage'] == 1
    assert result['irrelevant_ratio'] == pytest.approx(1/3)


def test_unknown_labels_do_not_become_irrelevant_or_produce_ndcg():
    from app.benchmark import ranking_metrics
    result = ranking_metrics(['unknown', 'a'], {'a': 2}, [['a']], k=5)
    assert result['recall'] == 1
    assert result['ndcg'] is None
    assert result['irrelevant_ratio'] is None
    assert result['unjudged_count'] == 1
    assert result['label_scope'] == 'annotated_evidence_only'


def test_duplicate_ranked_ids_are_rejected():
    from app.benchmark import ranking_metrics
    with pytest.raises(ValueError):
        ranking_metrics(['a', 'a'], {'a': 1}, [['a']], k=5)


def test_group_alternatives_and_unanswerable_metrics():
    from app.benchmark import ranking_metrics
    assert ranking_metrics(['b'], {'a': 1, 'b': 1}, [['a', 'b']], k=5)['evidence_group_coverage'] == 1
    empty = ranking_metrics(['unknown'], {}, [], k=5)
    assert empty['recall'] is None and empty['evidence_group_coverage'] is None


def test_quantiles_small_samples_and_invalid_numbers():
    from app.benchmark import latency_summary
    assert latency_summary([1, 2, 3, 4]) == {'count': 4, 'p50': 2.5, 'p95': 3.85}
    assert latency_summary([])['p50'] is None
    with pytest.raises(ValueError):
        latency_summary([float('nan')])


def test_frozen_evidence_requires_exact_text_hash_and_no_traversal(tmp_path):
    from app.benchmark import validate_evidence
    import hashlib
    content = 'Only full-time employees qualify. Prior approval is required.'
    (tmp_path / 'policy.md').write_text(content, encoding='utf-8')
    item = {'path': 'policy.md', 'quote': 'Prior approval is required.',
            'sha256': hashlib.sha256(content.encode()).hexdigest()}
    assert validate_evidence(tmp_path, item)
    with pytest.raises(ValueError):
        validate_evidence(tmp_path, {**item, 'quote': 'Approval is optional.'})
    with pytest.raises(ValueError):
        validate_evidence(tmp_path, {**item, 'path': '../outside.md'})


def test_split_assignment_never_splits_a_source_cluster():
    from app.benchmark import assign_split
    for cluster in ['leave', 'benefits-us', 'contracts']:
        assert assign_split(cluster) == assign_split(cluster)
        assert assign_split(cluster) in {'development', 'validation', 'test'}


def test_explicit_gold_proxy_does_not_claim_semantic_noise_is_measured():
    from app.benchmark import strict_gold_proxy
    result = strict_gold_proxy(['b', 'a'], ['a', 'b'], ['a'], k=10)
    assert result['ndcg'] == pytest.approx(1/math.log2(3))
    assert result['non_gold_fraction'] == .5
    assert result['semantic_irrelevant_ratio'] is None
