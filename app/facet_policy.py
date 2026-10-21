"""Conservative question-only facets and identity-preserving candidate fusion."""
import re

POLICY_VERSION = 'facet_interleave_v1'


def plan_subqueries(question: str) -> list[str]:
    # Only explicit structures are supported; no gold data, model planning or implied facts.
    match = re.match(r'^([^。？！?]+?)(都(?:属于|需要|可以|能够|能|是|有|适用)[^。？！?]*[？?])', question)
    if match:
        items = [s.strip() for s in match[1].split('、')]
        if 3 <= len(items) <= 3 and all(items):
            return [item + match[2][1:] for item in items]
    if '请结合' in question:
        clauses = [s.strip(' ，,；;') for s in re.findall(r'[^。？！?]+[？?]', question)]
        if 2 <= len(clauses) <= 3:
            return clauses
    return []


def interleave_rankings(rankings: list[list[dict]]) -> list[dict]:
    if not rankings or not rankings[0]:
        raise ValueError('Nonempty whole-query ranking required')
    def identity(chunks):
        result = {}
        for c in chunks:
            cid = c.get('chunk_id')
            if not isinstance(cid, str) or not cid or cid in result:
                raise ValueError('Missing or duplicate chunk identity')
            result[cid] = (c['file_path'], c['content'], c.get('content_headings'))
        return result
    expected = identity(rankings[0])
    if any(identity(r) != expected for r in rankings[1:]):
        raise ValueError('Branch candidate identity/content changed')
    output, seen = [], set()
    for position in range(len(rankings[0])):
        for ranking in rankings:
            chunk = ranking[position]
            if chunk['chunk_id'] not in seen:
                seen.add(chunk['chunk_id'])
                output.append(dict(chunk))
    return output


def rank_with_facets(question, chunks, rank_query, *, whole=None):
    whole = rank_query(question, chunks) if whole is None else whole
    if whole.get('error_kind') is not None or whole.get('ranked_chunks') is None:
        return {'strategy': 'whole_query_failed', 'ranked_chunks': None, 'whole': whole, 'branches': []}
    queries = plan_subqueries(question)
    result = {'strategy': 'whole_query_rerank', 'ranked_chunks': whole['ranked_chunks'],
              'whole': whole, 'subqueries': queries, 'branches': []}
    if not queries:
        return result
    for subquery in queries:
        record = rank_query(subquery, chunks)
        result['branches'].append({'query': subquery, 'collection': record})
        if record.get('error_kind') is not None or record.get('ranked_chunks') is None:
            result.update(strategy='fallback_whole_query', fallback_reason='facet_request_failed')
            return result
    try:
        result['ranked_chunks'] = interleave_rankings(
            [whole['ranked_chunks']] + [b['collection']['ranked_chunks'] for b in result['branches']])
        result['strategy'] = POLICY_VERSION
    except (ValueError, KeyError, TypeError):
        result.update(strategy='fallback_whole_query', fallback_reason='facet_identity_mismatch')
    return result
