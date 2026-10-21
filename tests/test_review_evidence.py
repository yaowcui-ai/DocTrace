from copy import deepcopy

import pytest

from app.review_evidence import select_cited_references


REFS = [
    {"reference_id": "1", "file_path": "one.md", "content": ["First full chunk.", "Second full chunk."]},
    {"reference_id": "2", "file_path": "two.md", "content": ["Other full chunk."]},
]


def test_cited_source_keeps_original_id_and_all_chunks_without_mutation():
    refs = deepcopy(REFS)
    result = select_cited_references("A claim. [2]", refs)
    assert result["references"] == [REFS[1]]
    assert result["citation_audit"]["cited_ids"] == ["2"]
    result["references"][0]["content"].append("modified")
    assert refs == REFS


def test_multiple_citations_preserve_first_citation_order_and_deduplicate():
    result = select_cited_references("A [2]. B [1]. Again [2].", REFS)
    assert result["references"] == [REFS[1], REFS[0]]


def test_known_nonstandard_citation_is_audited_without_rewriting():
    result = select_cited_references("A [reference_id: 1].", REFS)
    assert result["references"] == [REFS[0]]
    assert result["citation_audit"]["format_valid"] is False


@pytest.mark.parametrize("text", ["No citations.", "Unknown [9].", "Known [1], unknown [9]."])
def test_missing_or_unknown_citation_does_not_silently_fall_back_to_other_sources(text):
    with pytest.raises(ValueError):
        select_cited_references(text, REFS)


def test_duplicate_source_ids_are_rejected():
    with pytest.raises(ValueError):
        select_cited_references("Claim [1].", [REFS[0], REFS[0]])
