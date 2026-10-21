"""Check coverage reporting with simulated responses, without real requests."""

import httpx2 as httpx

from app.evaluate import evaluate_case


CASE = {
    "id": "HR-D02", "question": "Must I apply 30 days in advance?",
    "expected_behavior": "answer", "required_points": [], "failure_conditions": [],
    "evidence": [{"file_path": "fund.md", "quote": "when possible"}],
}


def collect(payload=None, status=200):
    def handler(request):
        return httpx.Response(status, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return evaluate_case(client, "http://app.test", CASE)


def test_success_adds_coverage_without_changing_raw_answer_or_manual_review():
    payload = {
        "response": "Apply in advance when possible.",
        "references": [{"reference_id": "1", "file_path": "fund.md",
                        "content": ["Apply 30 days in advance when possible."]}],
        "response_time": 1.0, "llm_generated": True,
    }
    record = collect(payload)
    assert record["evidence_coverage"]["coverage"] == 1.0
    assert record["result"] == payload
    assert record["review"]["answer_correct"] is None


def test_http_failure_is_not_scored_as_zero_coverage():
    record = collect(status=503)
    assert record["error_kind"] == "http_error"
    assert record["evidence_coverage"]["status"] == "not_evaluated"
    assert record["evidence_coverage"]["coverage"] is None


def test_placeholder_without_generation_or_references_is_not_evaluated():
    record = collect({"response": "No relevant context found for the query.",
                      "references": [], "response_time": 1.0, "llm_generated": False})
    assert record["evidence_coverage"]["status"] == "not_evaluated"


def test_generated_answer_without_sources_has_zero_returned_evidence_coverage():
    record = collect({"response": "I cannot answer from the documents.",
                      "references": [], "response_time": 1.0, "llm_generated": True})
    assert record["evidence_coverage"]["status"] == "checked"
    assert record["evidence_coverage"]["coverage"] == 0.0
