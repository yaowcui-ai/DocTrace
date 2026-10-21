import pytest

from app import citation_audit


REFERENCES = [
    {"reference_id": "1", "file_path": "pto.md", "content": ["Six days notice."]},
    {"reference_id": "3", "file_path": "leave.md", "content": ["Manager coordination."]},
]


def test_standard_known_citations_are_reported():
    result = citation_audit.audit_citations("Notice [1], coordination [3].", REFERENCES)
    assert result["cited_ids"] == ["1", "3"]
    assert result["unknown_ids"] == []
    assert result["nonstandard_markers"] == []
    assert result["has_citations"] is True
    assert result["ids_valid"] is True
    assert result["format_valid"] is True


@pytest.mark.parametrize("identifier", ["2", "0", "01"])
def test_unknown_ids_are_not_silently_remapped(identifier):
    result = citation_audit.audit_citations(f"Rule [{identifier}].", REFERENCES)
    assert result["unknown_ids"] == [identifier]
    assert result["ids_valid"] is False


def test_observed_provider_format_is_flagged_without_losing_the_id():
    result = citation_audit.audit_citations("Notice [reference_id: 1].", REFERENCES)
    assert result["cited_ids"] == ["1"]
    assert result["ids_valid"] is True
    assert result["format_valid"] is False
    assert result["nonstandard_markers"] == ["[reference_id: 1]"]


def test_repeated_citations_keep_first_appearance_order():
    result = citation_audit.audit_citations("Rule [3], [1], again [3].", REFERENCES)
    assert result["cited_ids"] == ["3", "1"]


def test_no_numeric_citations_are_identified_separately():
    result = citation_audit.audit_citations("Cannot confirm from evidence. [PTO]", REFERENCES)
    assert result["cited_ids"] == []
    assert result["has_citations"] is False


def test_known_id_does_not_grade_an_unsupported_claim_as_correct():
    result = citation_audit.audit_citations("The salary is 9999. [1]", REFERENCES)
    assert result["ids_valid"] is True
    assert "answer_correct" not in result
