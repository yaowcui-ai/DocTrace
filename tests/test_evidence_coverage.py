"""Offline checks for gold-quote coverage; no model or HTTP calls."""

from app import evaluate


GOLD = [{"file_path": "fund.md", "quote": "30 days when possible"}]


def test_quote_must_be_in_the_correct_file():
    references = [{"file_path": "leave.md", "content": ["30 days when possible"]}]
    result = evaluate.check_evidence_coverage(GOLD, references)
    assert result["matched_count"] == 0
    assert result["coverage"] == 0.0
    assert result["checks"][0]["found"] is False


def test_multiple_gold_items_are_checked_separately():
    gold = GOLD + [{"file_path": "pto.md", "quote": "six business days"}]
    references = [{"file_path": "fund.md", "content": ["Submit 30 days when possible."]}]
    result = evaluate.check_evidence_coverage(gold, references)
    assert result["expected_count"] == 2
    assert result["matched_count"] == 1
    assert result["coverage"] == 0.5
    assert result["status"] == "checked"


def test_duplicate_chunks_do_not_increase_gold_matches():
    references = [{"file_path": "fund.md", "content": [GOLD[0]["quote"]] * 2}]
    result = evaluate.check_evidence_coverage(GOLD, references)
    assert result["matched_count"] == 1
    assert result["coverage"] == 1.0


def test_no_gold_is_not_applicable_instead_of_perfect():
    result = evaluate.check_evidence_coverage([], [])
    assert result["status"] == "not_applicable"
    assert result["coverage"] is None


def test_missing_response_is_not_a_retrieval_miss():
    result = evaluate.check_evidence_coverage(GOLD, None)
    assert result["status"] == "not_evaluated"
    assert result["matched_count"] is None
    assert result["coverage"] is None


def test_empty_references_or_missing_content_do_not_match():
    for references in ([], [{"file_path": "fund.md", "content": None}]):
        result = evaluate.check_evidence_coverage(GOLD, references)
        assert result["matched_count"] == 0
        assert result["coverage"] == 0.0
