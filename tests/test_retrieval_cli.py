"""Offline CLI checks for retrieval and end-to-end evaluation dispatch."""

import hashlib
import json

import httpx2 as httpx
import pytest

from app import evaluate
from app.config import Settings


def prepare(monkeypatch, tmp_path):
    (tmp_path / "evaluation").mkdir()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    content = b"test document"
    (corpus / "policy.md").write_bytes(content)
    (corpus / "manifest.json").write_text(json.dumps({"documents": [{
        "document_id": "policy", "cleaned_file": "policy.md",
        "cleaned_sha256": hashlib.sha256(content).hexdigest(),
    }]}), encoding="utf-8")
    case = {"id": "C1", "type": "test", "question": "What is the rule?",
            "expected_behavior": "answer", "required_points": [],
            "failure_conditions": [],
            "evidence": [{"file_path": "policy.md", "quote": "rule"}]}
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"dataset_id": "cli-test", "split": "development",
        "corpus_id": "test", "corpus_manifest": "corpus/manifest.json",
        "cases": [case, {**case, "id": "C2"}]}), encoding="utf-8")
    monkeypatch.setattr(evaluate, "PROJECT_ROOT", tmp_path)
    return dataset


def test_retrieval_dry_run_does_not_load_credentials_or_send_requests(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Dry run must not load credentials or create HTTP client")

    monkeypatch.setattr(evaluate, "load_settings", fail, raising=False)
    monkeypatch.setattr(httpx, "Client", fail)
    evaluate.main(["--retrieval-only", "--all", "--dry-run"])


def test_retrieval_batch_keeps_failure_and_reports_real_target(monkeypatch, tmp_path):
    dataset = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluate, "load_settings", lambda: Settings(
        lightrag_url="http://rag.test", lightrag_api_key="test-secret-key"), raising=False)
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "http://rag.test/query/data"
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "success", "data": {"chunks": [
            {"reference_id": "1", "file_path": "policy.md", "content": "rule"}]}})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    evaluate.main(["--dataset", str(dataset), "--retrieval-only", "--all"])
    files = list((tmp_path / "evaluation/runs").glob("*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert report["evaluation_kind"] == "retrieval_only"
    assert report["base_url"] == "http://rag.test"
    assert report["endpoint"] == "/query/data"
    assert report["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert report["records"][0]["error_kind"] == "http_error"
    assert report["records"][1]["evidence_coverage"]["coverage"] == 1.0
    assert report["status"] == "completed_unscored"
    assert "test-secret-key" not in files[0].read_text(encoding="utf-8")


@pytest.mark.parametrize("endpoint, kind, flags", [
    ("/ask", "end_to_end", []),
    ("/ask/optimized", "optimized_end_to_end", ["--endpoint", "/ask/optimized"]),
])
def test_doctrace_paths_do_not_load_upstream_credentials(monkeypatch, tmp_path, endpoint, kind, flags):
    dataset = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluate, "login_evaluation_client", lambda *args: None)

    def fail(*args, **kwargs):
        pytest.fail("End-to-end evaluation must use DocTrace, not load upstream settings")

    monkeypatch.setattr(evaluate, "load_settings", fail, raising=False)

    def handler(request):
        assert str(request.url) == "http://127.0.0.1:8001" + endpoint
        return httpx.Response(200, json={"response": "rule", "references": [],
                                       "response_time": 1.0, "llm_generated": True})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    evaluate.main(["--dataset", str(dataset), "--case", "C1", "--login-user", "testuser"] + flags)
    report = json.loads(next((tmp_path / "evaluation/runs").glob("*.json")).read_text(encoding="utf-8"))
    assert report["evaluation_kind"] == kind
    assert report["endpoint"] == endpoint
    assert report["mode_expected"] is None


def test_answer_dataset_bound_to_optimized_endpoint_rejects_legacy_route_offline(monkeypatch,tmp_path):
    dataset=prepare(monkeypatch,tmp_path)
    data=json.loads(dataset.read_text(encoding='utf-8'))
    data['expected_endpoint']='/ask/optimized'
    dataset.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(SystemExit):
        evaluate.main(['--dataset',str(dataset),'--case','C1','--dry-run'])


def test_retrieval_mode_cannot_be_combined_with_optimized_answer_endpoint():
    with pytest.raises(SystemExit):
        evaluate.main(["--retrieval-only", "--endpoint", "/ask/optimized", "--all", "--dry-run"])


@pytest.mark.parametrize("mode", ["naive", "mix"])
def test_explicit_retrieval_mode_is_sent_and_graph_counts_preserved(monkeypatch, tmp_path, mode):
    dataset = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluate, "load_settings", lambda: Settings("http://rag.test", "secret"))
    def handler(request):
        payload = json.loads(request.content)
        assert payload == {"query": "What is the rule?", "mode": mode, "enable_rerank": False}
        return httpx.Response(200, json={"status": "success", "data": {
            "chunks": [{"reference_id": "1", "file_path": "policy.md", "content": "rule"}],
            "entities": [{"entity_name": "Policy"}],
            "relationships": [{"src_id": "Policy", "tgt_id": "Employee"}],
        }, "metadata": {"note": "preserve graph result"}})
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    evaluate.main(["--dataset", str(dataset), "--retrieval-only", "--mode", mode, "--case", "C1"])
    report = json.loads(next((tmp_path/'evaluation/runs').glob('*.json')).read_text(encoding='utf-8'))
    record = report["records"][0]
    assert report["mode_expected"] == mode
    assert report["request_options"] == {"mode": mode, "enable_rerank": False}
    assert record["mode"] == mode
    assert record["retrieved_entity_count"] == 1
    assert record["retrieved_relationship_count"] == 1
    assert record["retrieved_characters"] == 4
    assert record["result"]["metadata"]["note"] == "preserve graph result"
    assert record["evidence_coverage"]["coverage"] == 1.0


@pytest.mark.parametrize("mode", ["naive", "mix"])
def test_retrieval_mode_dry_run_is_offline(monkeypatch, mode):
    def fail(*args, **kwargs): pytest.fail("mode dry run must not contact upstream or read keys")
    monkeypatch.setattr(evaluate, "load_settings", fail)
    monkeypatch.setattr(httpx, "Client", fail)
    evaluate.main(["--retrieval-only", "--mode", mode, "--case", "HR-D06", "--dataset", str(evaluate.PROJECT_ROOT/'evaluation/hr_dev_v3.json'), "--dry-run"])


def test_explicit_mode_cannot_silently_change_or_be_ignored_by_answer_evaluation():
    with pytest.raises(SystemExit):
        evaluate.main(["--mode", "mix", "--all", "--dry-run"])


def test_explicit_local_target_is_used_without_mutating_settings(monkeypatch, tmp_path):
    dataset = prepare(monkeypatch, tmp_path)
    settings = Settings('http://127.0.0.1:9622', 'secret')
    monkeypatch.setattr(evaluate, 'load_settings', lambda: settings)

    def handler(request):
        assert str(request.url) == 'http://127.0.0.1:9623/query/data'
        assert request.headers['X-API-Key'] == 'secret'
        return httpx.Response(200, json={'status': 'success', 'data': {'chunks': []}})

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    evaluate.main(['--dataset', str(dataset), '--retrieval-only', '--case', 'C1',
                   '--lightrag-url', 'http://127.0.0.1:9623'])
    assert settings.lightrag_url == 'http://127.0.0.1:9622'
    report = json.loads(next((tmp_path/'evaluation/runs').glob('*.json')).read_text(encoding='utf-8'))
    assert report['base_url'] == 'http://127.0.0.1:9623'


@pytest.mark.parametrize('flags', [
    ['--lightrag-url', 'http://127.0.0.1:9622', '--retrieval-only'],
    ['--retrieval-only'],
    [],
])
def test_bound_dataset_rejects_wrong_or_unspecified_target_offline(monkeypatch, tmp_path, flags, capsys):
    dataset = prepare(monkeypatch, tmp_path)
    data = json.loads(dataset.read_text(encoding='utf-8'))
    data.update(retrieval_only=True, expected_retrieval_url='http://127.0.0.1:9623')
    dataset.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(SystemExit):
        evaluate.main(['--dataset', str(dataset), '--case', 'C1', '--dry-run'] + flags)
    assert 'dataset' in capsys.readouterr().err.lower()


def test_explicit_target_dry_run_does_not_read_keys_or_contact_server(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail('Dry run must remain offline')
    monkeypatch.setattr(evaluate, 'load_settings', fail)
    monkeypatch.setattr(httpx, 'Client', fail)
    evaluate.main(['--all', '--dry-run', '--retrieval-only',
                   '--lightrag-url', 'http://127.0.0.1:9623'])


def test_target_option_is_not_silently_ignored_by_answer_evaluation(capsys):
    with pytest.raises(SystemExit):
        evaluate.main(['--all', '--dry-run', '--lightrag-url', 'http://127.0.0.1:9623'])
    assert '--retrieval-only' in capsys.readouterr().err


def test_explicit_total_token_budget_is_sent_and_recorded(monkeypatch, tmp_path):
    dataset = prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluate, 'load_settings', lambda: Settings('http://rag.test', 'secret'))
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload == {'query': 'What is the rule?', 'mode': 'mix',
                           'enable_rerank': False, 'max_total_tokens': 40000}
        return httpx.Response(200, json={'status': 'success', 'data': {'chunks': []}})

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    evaluate.main(['--dataset', str(dataset), '--retrieval-only', '--case', 'C1',
                   '--mode', 'mix', '--max-total-tokens', '40000'])
    report = json.loads(next((tmp_path/'evaluation/runs').glob('*.json')).read_text(encoding='utf-8'))
    assert len(requests) == 1
    assert report['request_options']['max_total_tokens'] == 40000
    assert report['records'][0]['max_total_tokens_requested'] == 40000


@pytest.mark.parametrize('budget', ['0', '-1', '3.5'])
def test_invalid_total_budget_is_rejected_before_request(budget, capsys):
    with pytest.raises(SystemExit):
        evaluate.main(['--retrieval-only', '--all', '--dry-run', '--max-total-tokens', budget])
    assert '--max-total-tokens' in capsys.readouterr().err


def test_total_budget_cannot_silently_modify_answer_evaluation(capsys):
    with pytest.raises(SystemExit):
        evaluate.main(['--all', '--dry-run', '--max-total-tokens', '40000'])
    assert '--retrieval-only' in capsys.readouterr().err


def test_budget_dry_run_does_not_contact_models(monkeypatch, capsys):
    def fail(*args, **kwargs): pytest.fail('Budget preview must be offline')
    monkeypatch.setattr(evaluate, 'load_settings', fail)
    monkeypatch.setattr(httpx, 'Client', fail)
    evaluate.main(['--all', '--retrieval-only', '--dry-run', '--max-total-tokens', '40000'])
    assert '40000' in capsys.readouterr().out


def test_medium_hr_target_dry_run_is_explicit_and_offline(monkeypatch, capsys):
    def fail(*args, **kwargs): pytest.fail('Preview must remain offline')
    monkeypatch.setattr(evaluate, 'load_settings', fail)
    monkeypatch.setattr(httpx, 'Client', fail)
    evaluate.main(['--all', '--retrieval-only', '--dry-run',
                   '--lightrag-url', 'http://127.0.0.1:9624'])
    assert 'Retrieval target: http://127.0.0.1:9624' in capsys.readouterr().out
