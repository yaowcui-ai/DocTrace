"""Reproducible ranking metrics; never silently interpret unjudged chunks as noise."""
import hashlib
import math
from pathlib import Path


def ranking_metrics(ranked_ids: list[str], relevance: dict[str, int], groups: list[list[str]], *, k: int) -> dict:
    if type(k) is not int or k < 1 or len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError('Positive k and unique ranked IDs are required')
    if any(type(grade) is not int or grade not in (0, 1, 2, 3) for grade in relevance.values()):
        raise ValueError('Relevance grades must be integers from 0 to 3')
    if any(not isinstance(group, list) or any(not isinstance(item, str) for item in group) for group in groups):
        raise ValueError('Evidence groups must contain alternative chunk IDs')
    selected = ranked_ids[:k]
    positives = {item for item, grade in relevance.items() if grade > 0}
    missing_labels = [item for item in selected if item not in relevance]
    hits = sum(item in positives for item in selected)
    reciprocal = next((1/rank for rank, item in enumerate(selected, 1) if item in positives), 0.0)
    complete = not missing_labels
    dcg = sum((2**relevance.get(item, 0)-1)/math.log2(rank+1) for rank, item in enumerate(selected, 1))
    idcg = sum((2**grade-1)/math.log2(rank+1) for rank, grade in enumerate(sorted(relevance.values(), reverse=True)[:k], 1))
    return {
        'k': k, 'returned_count': len(selected), 'annotated_positive_count': len(positives),
        'recall': hits/len(positives) if positives else None,
        'mrr': reciprocal if positives else None,
        'ndcg': dcg/idcg if complete and idcg else None,
        'evidence_group_coverage': sum(bool(set(group).intersection(selected)) for group in groups)/len(groups) if groups else None,
        'irrelevant_ratio': sum(relevance[item] == 0 for item in selected)/len(selected) if selected and complete else None,
        'unjudged_count': len(missing_labels),
        'label_scope': 'fully_judged_returned_list' if complete else 'annotated_evidence_only',
    }


def strict_gold_proxy(ranked_ids, candidate_ids, gold_ids, *, k=10):
    """Explicit closed-gold proxy; absence of a marked quote is NOT semantic irrelevance."""
    if not set(ranked_ids).issubset(candidate_ids):
        raise ValueError('Ranking contains an unknown candidate identity')
    gold = set(gold_ids)
    labels = {key: 2 if key in gold else 0 for key in set(candidate_ids).union(gold)}
    measured = ranking_metrics(ranked_ids, labels, [], k=k)
    return {'ndcg': measured['ndcg'], 'non_gold_fraction': measured['irrelevant_ratio'],
        'semantic_irrelevant_ratio': None, 'judgment_scope': 'strict_frozen_evidence_proxy_not_semantic_relevance'}


def latency_summary(values: list[float]) -> dict:
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError('Latency must be finite and non-negative')
    ordered = sorted(values)
    def percentile(fraction):
        if not ordered:
            return None
        position = (len(ordered)-1)*fraction
        lo, hi = math.floor(position), math.ceil(position)
        return round(ordered[lo] + (ordered[hi]-ordered[lo])*(position-lo), 6)
    return {'count': len(ordered), 'p50': percentile(.5), 'p95': percentile(.95)}


def validate_evidence(root: Path, evidence: dict) -> bool:
    root = root.resolve()
    path = (root/evidence['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Evidence path escapes frozen corpus or does not exist')
    raw = path.read_bytes()
    quote = evidence.get('quote')
    if hashlib.sha256(raw).hexdigest() != evidence.get('sha256'):
        raise ValueError('Source content hash mismatch')
    if not isinstance(quote, str) or not quote.strip() or quote not in raw.decode('utf-8'):
        raise ValueError('Exact evidence quote is absent')
    return True


def assign_split(source_cluster: str) -> str:
    """Group by policy source cluster BEFORE observing outcomes; do not split rewrites."""
    bucket = int(hashlib.sha256(('doctrace-upgrade-v1:' + source_cluster).encode()).hexdigest()[:8], 16) % 10
    return 'development' if bucket < 3 else 'validation' if bucket < 5 else 'test'
