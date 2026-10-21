"""Validate provider index mapping without calling any model."""

from copy import deepcopy

import pytest

from app.rerank import map_rerank_results


CHUNKS = [
    {"chunk_id": "chunk-A", "file_path": "fund.md", "reference_id": "4", "content": "Fund policy"},
    {"chunk_id": "chunk-B", "file_path": "leave.md", "reference_id": "2", "content": "Leave policy"},
]


def test_maps_provider_order_to_original_chunks_without_mutation():
    chunks = deepcopy(CHUNKS)
    results = [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.3}]
    result = map_rerank_results(chunks, results)
    assert [c["chunk_id"] for c in result] == ["chunk-B", "chunk-A"]
    assert result[0]["file_path"] == "leave.md"
    assert result[0]["reference_id"] == "2"
    assert result[0]["content"] == "Leave policy"
    assert result[0]["rerank_score"] == 0.9
    assert result[0]["original_position"] == 2
    assert chunks == CHUNKS
    assert result[0] is not chunks[1]


def test_incomplete_response_is_rejected_in_full_ranking_experiment():
    with pytest.raises(ValueError):
        map_rerank_results(CHUNKS, [{"index": 0, "relevance_score": 0.9}])


def test_duplicate_indices_are_rejected():
    with pytest.raises(ValueError):
        map_rerank_results(CHUNKS, [
            {"index": 0, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.3}])


@pytest.mark.parametrize("index", [-1, 2, True, 0.0, "0"])
def test_invalid_indices_are_rejected(index):
    with pytest.raises(ValueError):
        map_rerank_results(CHUNKS, [
            {"index": index, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.3}])


@pytest.mark.parametrize("score", [float("nan"), float("inf"), "0.9", True, None])
def test_invalid_scores_are_rejected(score):
    with pytest.raises(ValueError):
        map_rerank_results(CHUNKS, [
            {"index": 0, "relevance_score": score}, {"index": 1, "relevance_score": 0.3}])


def test_missing_fields_are_rejected():
    with pytest.raises(ValueError):
        map_rerank_results(CHUNKS, [{"index": 0}, {"index": 1, "relevance_score": 0.3}])


def test_empty_input_can_be_mapped_without_a_request():
    assert map_rerank_results([], []) == []
