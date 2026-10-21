from copy import deepcopy

import pytest

from app import context_selection


CHUNKS = [
    {"chunk_id": "A", "file_path": "a.md", "content": "aaaa", "rerank_score": 0.9},
    {"chunk_id": "B", "file_path": "b.md", "content": "bbbbb", "rerank_score": 0.8},
    {"chunk_id": "C", "file_path": "c.md", "content": "ccc", "rerank_score": 0.7},
]


def test_whole_chunks_fit_budget_without_mutating_inputs():
    chunks = deepcopy(CHUNKS)
    result = context_selection.select_context(chunks, max_chars=8)
    assert [c["chunk_id"] for c in result["selected_chunks"]] == ["A", "C"]
    assert result["characters"] == 7
    assert [x["reason"] for x in result["decisions"]] == ["selected", "budget_exceeded", "selected"]
    assert chunks == CHUNKS
    assert result["selected_chunks"][0]["rerank_score"] == 0.9
    assert result["selected_chunks"][0] is not chunks[0]


def test_duplicate_chunk_id_is_not_counted_twice():
    result = context_selection.select_context([CHUNKS[0], CHUNKS[0], CHUNKS[2]], max_chars=10)
    assert len(result["selected_chunks"]) == 2
    assert result["characters"] == 7
    assert result["decisions"][1]["reason"] == "duplicate_id"


def test_oversize_chunk_is_not_silently_cut():
    result = context_selection.select_context([CHUNKS[0]], max_chars=3)
    assert result["selected_chunks"] == []
    assert result["characters"] == 0
    assert result["decisions"][0]["reason"] == "budget_exceeded"


def test_empty_candidates_are_valid():
    result = context_selection.select_context([], max_chars=10)
    assert result == {"selected_chunks": [], "characters": 0, "decisions": []}


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_budget_is_rejected(budget):
    with pytest.raises(ValueError):
        context_selection.select_context(CHUNKS, max_chars=budget)
