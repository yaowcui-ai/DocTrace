"""Keep grouped coverage separate from legacy exact-quote coverage."""

import httpx2 as httpx
import pytest

from app.config import Settings
from app.evaluate import evaluate_case, evaluate_retrieval_case


CASE = {"id": "C1", "question": "How much notice?", "expected_behavior": "answer",
        "required_points": [], "failure_conditions": [],
        "evidence": [{"file_path": "pto.md", "quote": "six days"}],
        "evidence_groups": [{"group_id": "notice", "alternatives": [
            {"file_path": "pto.md", "quote": "six days"},
            {"file_path": "general.md", "quote": "PTO needs six days"}]}]}


@pytest.mark.parametrize("retrieval", [False, True])
def test_both_paths_keep_legacy_and_group_metrics_separate(retrieval):
    def handler(request):
        if retrieval:
            return httpx.Response(200, json={"status": "success", "data": {"chunks": [
                {"reference_id": "1", "file_path": "general.md", "content": "PTO needs six days"}]}})
        return httpx.Response(200, json={"response": "six days", "references": [
            {"reference_id": "1", "file_path": "general.md", "content": ["PTO needs six days"]}],
            "llm_generated": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if retrieval:
            record = evaluate_retrieval_case(client, Settings("http://rag.test", "key"), CASE)
        else:
            record = evaluate_case(client, "http://app.test", CASE)
    assert record["evidence_coverage"]["coverage"] == 0.0
    assert record["evidence_group_coverage"]["coverage"] == 1.0


def test_failed_retrieval_does_not_score_groups_as_missing():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        record = evaluate_retrieval_case(client, Settings("http://rag.test", "key"), CASE)
    assert record["evidence_group_coverage"]["status"] == "not_evaluated"
