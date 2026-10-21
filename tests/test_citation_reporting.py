import httpx2 as httpx
import pytest

from app.evaluate import evaluate_case


CASE = {"id": "C1", "question": "Question", "expected_behavior": "answer",
        "required_points": [], "failure_conditions": [], "evidence": []}


@pytest.mark.parametrize("text, ids_valid, format_valid, has_citations", [
    ("Rule [1]", True, True, True),
    ("Rule [reference_id: 1]", True, False, True),
    ("Rule [2]", False, True, True),
    ("Cannot confirm.", True, True, False),
])
def test_generated_answer_gets_audit_without_modification_or_automatic_grading(
    text, ids_valid, format_valid, has_citations
):
    payload = {"response": text, "references": [
        {"reference_id": "1", "file_path": "policy.md", "content": ["Rule"]}],
        "response_time": 1.0, "llm_generated": True}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        record = evaluate_case(client, "http://app.test", CASE)
    assert record["result"] == payload
    assert record["citation_audit"]["status"] == "checked"
    assert record["citation_audit"]["ids_valid"] is ids_valid
    assert record["citation_audit"]["format_valid"] is format_valid
    assert record["citation_audit"]["has_citations"] is has_citations
    assert record["review"]["citation_consistent"] is None


def test_no_response_is_not_evaluated():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        record = evaluate_case(client, "http://app.test", CASE)
    assert record["citation_audit"]["status"] == "not_evaluated"


def test_program_written_insufficient_evidence_reply_is_not_model_citation_failure():
    payload = {"response": "Insufficient evidence.", "references": [], "llm_generated": False}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        record = evaluate_case(client, "http://app.test", CASE)
    assert record["citation_audit"]["status"] == "not_applicable"
