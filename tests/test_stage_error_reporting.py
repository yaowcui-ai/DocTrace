import httpx2 as httpx
import pytest

from app.evaluate import evaluate_case
from app.lightrag_client import UpstreamError


CASE = {"id": "C1", "question": "Question", "expected_behavior": "answer",
        "required_points": [], "failure_conditions": [], "evidence": []}


def test_upstream_error_can_carry_a_stage_without_changing_legacy_message():
    error = UpstreamError(504, "Service timed out", stage="重排")
    assert error.stage == "重排"
    assert str(error) == "Service timed out"
    assert UpstreamError(502, "Legacy error").stage is None


@pytest.mark.parametrize("stage", ["检索", "重排", "回答模型"])
def test_evaluation_retains_structured_stage_without_raw_error_text(stage):
    body = {"detail": {"stage": stage, "message": "secret-value"}}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(504, json=body))) as client:
        record = evaluate_case(client, "http://app.test", CASE, endpoint="/ask/optimized")
    assert record["error_kind"] == "http_error"
    assert record["error_stage"] == stage
    assert record["result"] is None
    assert "secret-value" not in str(record)


def test_legacy_error_or_unknown_stage_is_not_guessed():
    for body in [{"detail": "Timeout"}, {"detail": {"stage": "secret-value"}}]:
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(504, json=body))) as client:
            record = evaluate_case(client, "http://app.test", CASE)
        assert record["error_stage"] is None
