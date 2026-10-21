import json

import httpx2 as httpx
import pytest

from app.evaluate import evaluate_case, main, run_cases, select_cases


CASE = {"id": "HR-D02", "question": "是否必须提前30天？", "expected_behavior": "answer", "required_points": ["保留when possible条件"], "failure_conditions": ["称一律拒绝"], "evidence": []}
ANSWER = {"response": "应尽可能提前30天。", "references": [{"reference_id": "1", "file_path": "hr_growth_development.md", "content": ["when possible"]}], "response_time": 1.2, "llm_generated": True}


def test_posts_to_doctrace_and_preserves_raw_answer_for_review():
    def handler(request):
        assert request.method == "POST" and str(request.url) == "http://app.test/ask"
        assert json.loads(request.content) == {"question": CASE["question"]}
        return httpx.Response(200, json=ANSWER)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = evaluate_case(client, "http://app.test", CASE)
    assert record["result"] == ANSWER
    assert record["retrieved_chunk_count"] == 1
    assert record["elapsed_seconds"] >= 0
    assert record["review"]["answer_correct"] is None
    assert record["required_points"] == CASE["required_points"]


@pytest.mark.parametrize("kind,expected", [("timeout", "timeout"), ("connection", "transport_error"), ("http", "http_error"), ("json", "invalid_response"), ("schema", "invalid_response")])
def test_failures_are_recorded_without_retry_or_raw_exception(kind, expected):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == "timeout": raise httpx.ReadTimeout("secret-value", request=request)
        if kind == "connection": raise httpx.ConnectError("secret-value", request=request)
        if kind == "http": return httpx.Response(504, text="secret-value")
        if kind == "json": return httpx.Response(200, text="secret-value")
        return httpx.Response(200, json={"response": 123})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        record = evaluate_case(client, "http://app.test", CASE)
    assert record["error_kind"] == expected
    assert record["result"] is None
    assert "secret-value" not in json.dumps(record)
    assert len(calls) == 1


def test_batch_keeps_failure_and_continues():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json=ANSWER)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = list(run_cases(client, "http://app.test", [CASE, {**CASE, "id": "HR-D03"}]))
    assert len(records) == 2
    assert records[0]["error_kind"] == "http_error"
    assert records[1]["result"] == ANSWER


def test_batch_yields_finished_case_before_requesting_next():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=ANSWER)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = run_cases(client, "http://app.test", [CASE, CASE])
        assert not calls
        assert next(records)["result"] == ANSWER
        assert len(calls) == 1


def test_unknown_case_fails_before_sending_requests():
    with pytest.raises(ValueError): select_cases({"cases": [CASE]}, "HR-D99")
    assert select_cases({"cases": [CASE]}, "HR-D02") == [CASE]


def test_dry_run_does_not_create_http_client(monkeypatch, capsys):
    def fail(*args, **kwargs):
        pytest.fail("Dry run must not create an HTTP client")
    monkeypatch.setattr(httpx, "Client", fail)
    main(["--all", "--dry-run"])
    assert "Selected cases: 8" in capsys.readouterr().out

def test_can_select_dataset(tmp_path, capsys):
    dataset_path = tmp_path / "custom.json"
    dataset_path.write_text(
        json.dumps({
            "dataset_id": "test_v2",
            "cases": [{**CASE, "type": "qualified_rule"}],
        }),
        encoding="utf-8",
    )

    main([
        "--dataset", str(dataset_path),
        "--case", "HR-D02",
        "--dry-run",
    ])

    assert "Dataset: test_v2" in capsys.readouterr().out