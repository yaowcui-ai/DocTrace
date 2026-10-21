"""Validate anchors in an offline model review, without deciding semantic truth.

Learning step: implement validate_grounding_review using the documented contract.
This module is not imported by the online application.
"""

from copy import deepcopy


ISSUE_KINDS = frozenset({
    "missing_condition",
    "weakened_requirement",
    "strengthened_requirement",
})

FINDING_FIELDS = frozenset({
    "kind", "answer_quote", "reference_id", "evidence_quote", "explanation",
})


def validate_grounding_review(
    review: dict,
    answer_text: str,
    references: list[dict],
) -> dict:
    # 1. 检查最外层结构，只允许 findings 字段。
    if not isinstance(review, dict) or set(review) != {"findings"}:
        raise ValueError("Review must contain exactly 'findings'.")

    findings = review["findings"]
    if not isinstance(findings, list):
        raise ValueError("Findings must be a list.")

    for finding in findings:
        # 2. 每条意见必须包含规定的五个字段。
        if not isinstance(finding, dict):
            raise ValueError("Each finding must be a dictionary.")

        if set(finding) != FINDING_FIELDS:
            raise ValueError("Finding fields are invalid.")

        # strip() 这里只判断是否为空白，不修改原文。
        if not all(
            isinstance(value, str) and value.strip()
            for value in finding.values()
        ):
            raise ValueError("Finding values must be nonblank strings.")

        # 3. 检查问题类型。
        if finding["kind"] not in ISSUE_KINDS:
            raise ValueError("Unknown issue kind.")

        # 4. 核验意见引用的答案原句必须真实存在。
        if finding["answer_quote"] not in answer_text:
            raise ValueError("Answer quote was not found.")

        # 5. 找到核验意见对应的来源。
        reference = next(
            (
                ref
                for ref in references
                if ref["reference_id"] == finding["reference_id"]
            ),
            None,
        )

        if reference is None:
            raise ValueError("Unknown reference ID.")

        # 6. 原文必须出现在该来源的某一个片段中。
        contents = reference.get("content") or []

        if not any(
            finding["evidence_quote"] in content
            for content in contents
        ):
            raise ValueError("Evidence quote was not found in this reference.")

    # 7. 返回独立副本，避免后续修改影响原始输入。
    return {
        "status": "issues_reported" if findings else "no_issues_reported",
        "findings": deepcopy(findings),
    }