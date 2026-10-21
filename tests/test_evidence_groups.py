"""Equivalent sources may satisfy one evidence requirement; requirements stay separate."""

import pytest

from app import evaluate


GROUPS = [
    {"group_id": "coordination", "alternatives": [
        {"file_path": "leave.md", "quote": "manager coordination"}]},
    {"group_id": "notice", "alternatives": [
        {"file_path": "pto.md", "quote": "six business days"},
        {"file_path": "philosophy.md", "quote": "PTO needs six business days"}]},
]


@pytest.mark.parametrize("notice", [
    {"file_path": "pto.md", "content": ["six business days"]},
    {"file_path": "philosophy.md", "content": ["PTO needs six business days"]},
])
def test_either_valid_alternative_satisfies_the_notice_group(notice):
    refs = [{"file_path": "leave.md", "content": ["manager coordination"]}, notice]
    result = evaluate.check_evidence_group_coverage(GROUPS, refs)
    assert result["status"] == "checked"
    assert result["expected_count"] == 2
    assert result["matched_count"] == 2
    assert result["coverage"] == 1.0


def test_two_notice_sources_do_not_replace_missing_coordination():
    refs = [{"file_path": "pto.md", "content": ["six business days"]},
            {"file_path": "philosophy.md", "content": ["PTO needs six business days"]}]
    result = evaluate.check_evidence_group_coverage(GROUPS, refs)
    assert result["matched_count"] == 1
    assert result["coverage"] == 0.5


def test_wrong_policy_file_does_not_satisfy_notice():
    result = evaluate.check_evidence_group_coverage(GROUPS, [
        {"file_path": "volunteer.md", "content": ["six business days"]}])
    assert result["matched_count"] == 0


def test_no_result_is_not_evaluated():
    result = evaluate.check_evidence_group_coverage(GROUPS, None)
    assert result["status"] == "not_evaluated"
    assert result["coverage"] is None


def test_no_groups_is_not_applicable():
    result = evaluate.check_evidence_group_coverage([], [])
    assert result["status"] == "not_applicable"
    assert result["coverage"] is None


def test_empty_alternative_group_is_invalid_annotation():
    with pytest.raises(ValueError):
        evaluate.check_evidence_group_coverage([{"group_id": "bad", "alternatives": []}], [])
