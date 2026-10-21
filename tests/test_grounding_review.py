"""Local contract checks; these tests do not call a review model."""

from copy import deepcopy

import pytest

from app.grounding_review import validate_grounding_review


ANSWER = "You may need evidence. PTO is available with manager coordination."
REFERENCES = [
    {"reference_id": "1", "file_path": "caregiver.md", "content": [
        "Eligibility will require evidence in accordance with local requirements.",
        "The document type may vary by location.",
    ]},
    {"reference_id": "2", "file_path": "pto.md", "content": [
        "If business critical deadlines will be missed, your Manager may ask you to change the dates.",
    ]},
]


def finding(**changes):
    value = {
        "kind": "weakened_requirement",
        "answer_quote": "may need evidence",
        "reference_id": "1",
        "evidence_quote": "will require evidence in accordance with local requirements",
        "explanation": "The source requires evidence; the answer makes it optional.",
    }
    value.update(changes)
    return value


def test_findings_keep_distinct_answer_and_evidence_anchors():
    second = finding(
        kind="missing_condition",
        answer_quote="PTO is available with manager coordination.",
        reference_id="2",
        evidence_quote="If business critical deadlines will be missed, your Manager may ask you to change the dates.",
        explanation="The added PTO advice omits the date-change condition.",
    )
    source = {"findings": [finding(), second]}
    result = validate_grounding_review(source, ANSWER, REFERENCES)
    assert result == {"status": "issues_reported", "findings": source["findings"]}


def test_no_findings_means_no_issues_reported_not_verified_correct():
    assert validate_grounding_review({"findings": []}, ANSWER, REFERENCES) == {
        "status": "no_issues_reported", "findings": [],
    }


def test_review_cannot_invent_a_sentence_in_the_answer():
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding(answer_quote="No evidence is ever needed.")]}, ANSWER, REFERENCES)


def test_unknown_reference_is_rejected():
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding(reference_id="9")]}, ANSWER, REFERENCES)


def test_real_quote_under_wrong_reference_is_rejected():
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding(reference_id="2")]}, ANSWER, REFERENCES)


def test_invented_evidence_quote_is_rejected():
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding(evidence_quote="Evidence is optional everywhere.")]}, ANSWER, REFERENCES)


def test_two_chunks_cannot_be_joined_to_manufacture_one_quote():
    quote = REFERENCES[0]["content"][0] + REFERENCES[0]["content"][1]
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding(evidence_quote=quote)]}, ANSWER, REFERENCES)


def test_none_content_cannot_support_a_finding():
    refs = [{"reference_id": "1", "file_path": "caregiver.md", "content": None}]
    with pytest.raises(ValueError):
        validate_grounding_review({"findings": [finding()]}, ANSWER, refs)


def test_strengthened_requirement_is_a_supported_review_category():
    answer = "You must submit 30 days in advance without exception."
    refs = [{"reference_id": "1", "file_path": "fund.md", "content": [
        "Your request should be submitted 30 days in advance when possible.",
    ]}]
    item = finding(kind="strengthened_requirement", answer_quote=answer,
        evidence_quote="30 days in advance when possible",
        explanation="The answer removes the when-possible qualification.")
    assert validate_grounding_review({"findings": [item]}, answer, refs)["status"] == "issues_reported"


@pytest.mark.parametrize("review", [
    None, [], {}, {"findings": None}, {"findings": "none"},
    {"findings": [], "passed": True}, {"findings": [None]},
    {"findings": [{"kind": "missing_condition"}]},
    {"findings": [finding(kind="unsupported_claim")]},
    {"findings": [finding(reference_id=1)]},
    {"findings": [finding(explanation="   ")]},
    {"findings": [finding(answer_quote="")]},
    {"findings": [dict(finding(), confidence=1.0)]},
])
def test_malformed_review_is_not_treated_as_clean_answer(review):
    with pytest.raises(ValueError):
        validate_grounding_review(review, ANSWER, REFERENCES)


def test_inputs_and_returned_findings_do_not_share_mutable_state():
    source = {"findings": [finding()]}
    refs = deepcopy(REFERENCES)
    before = deepcopy((source, refs))
    result = validate_grounding_review(source, ANSWER, refs)
    assert (source, refs) == before
    result["findings"][0]["explanation"] = "Changed after validation"
    assert (source, refs) == before
