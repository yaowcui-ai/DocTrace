"""Execute hash-checked upstream functions; never approximate token truncation."""
import asyncio
from pathlib import Path
import pytest


def test_snapshot_refuses_changed_bytes_before_compilation(tmp_path):
    from app.native_snapshot import load_selector
    path = tmp_path/'utils.py'
    path.write_text('raise RuntimeError("must never execute")', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        load_selector(path)


def test_native_snapshot_reranks_before_topk_and_counts_rendered_tokens():
    from app.native_snapshot import replay_rows
    pool = [{'chunk_id': 'a', 'file_path': 'a.md', 'content': 'unrelated'},
            {'chunk_id': 'b', 'file_path': 'b.md', 'content': 'approval required'}]
    rows = [{'case_id': 'test', 'query': 'approval?', 'tokenizer': 'gpt-4o-mini',
             'top_k': 1, 'budget': 1000, 'scores': [{'index': 1, 'relevance_score': .9}, {'index': 0, 'relevance_score': .1}],
             'variants': {'B0': pool, 'B2': list(reversed(pool)), 'B3': list(reversed(pool))}}]
    result = asyncio.run(replay_rows(rows))[0]['variants']
    assert result['B0']['selected_ids'] == ['a']
    assert result['B1']['selected_ids'] == result['B2']['selected_ids'] == ['b']
    assert result['B1']['rendered_chunk_tokens'] > 0
