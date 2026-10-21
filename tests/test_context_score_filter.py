"""Score eligibility and length budget must be separate selection conditions."""

import pytest

from app.context_selection import select_context


def chunk(chunk_id, content, score):
    return {"chunk_id": chunk_id, "file_path": "policy.md", "content": content,
            "rerank_score": score}


def test_low_score_is_excluded_even_when_budget_remains():
    chunks = [chunk("A", "aaaa", 0.9), chunk("B", "bb", 0.1), chunk("C", "ccc", 0.8)]
    original = select_context(chunks, max_chars=10)
    filtered = select_context(chunks, max_chars=10, min_score=0.3)
    assert len(original["selected_chunks"]) == 3
    assert [c["chunk_id"] for c in filtered["selected_chunks"]] == ["A", "C"]
    assert filtered["characters"] == 7
    assert filtered["decisions"][1]["reason"] == "below_min_score"


def test_score_equal_to_threshold_is_retained():
    result = select_context([chunk("A", "a", 0.3)], max_chars=10, min_score=0.3)
    assert len(result["selected_chunks"]) == 1


@pytest.mark.parametrize("score", [None, "0.5", True, float("nan"), float("inf")])
def test_invalid_candidate_score_is_not_treated_as_a_match(score):
    with pytest.raises(ValueError):
        select_context([chunk("A", "a", score)], max_chars=10, min_score=0.3)


@pytest.mark.parametrize("threshold", [True, "0.3", float("nan"), float("inf")])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError):
        select_context([], max_chars=10, min_score=threshold)


def test_all_low_scores_returns_empty_context_without_filling_budget():
    result = select_context([chunk("A", "a", 0.01)], max_chars=10, min_score=0.3)
    assert result["selected_chunks"] == []
    assert result["characters"] == 0
