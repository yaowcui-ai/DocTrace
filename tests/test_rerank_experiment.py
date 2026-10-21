import hashlib
import json

import httpx2 as httpx
import pytest

from app import rerank_experiment
from app.rerank_config import RerankSettings


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(rerank_experiment, "PROJECT_ROOT", tmp_path)
    case = {"id": "C1", "question": "Find alpha", "evidence": [
        {"file_path": "a.md", "quote": "alpha"}],
        "evidence_groups": [{"group_id": "alpha", "alternatives": [
            {"file_path": "a.md", "quote": "alpha"}]}]}
    (tmp_path / "corpus.json").write_text('{"documents": []}', encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"dataset_id": "test", "corpus_id": "test-corpus",
        "corpus_manifest": "corpus.json", "cases": [case]}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"run_id": "source-run", "evaluation_kind": "retrieval_only",
        "dataset_id": "test", "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "corpus_id": "test-corpus", "corpus_sha256_by_document": {}, "records": [{
            "case_id": "C1", "question": "Find alpha", "http_status": 200, "error_kind": None,
            "result": {"status": "success", "data": {"chunks": [
                {"chunk_id": "A", "reference_id": "1", "file_path": "a.md", "content": "alpha"},
                {"chunk_id": "B", "reference_id": "2", "file_path": "b.md", "content": "beta"}]}}}]}), encoding="utf-8")
    return dataset, baseline


def test_dry_run_needs_neither_credentials_nor_network(tmp_path, monkeypatch):
    dataset, baseline = prepare(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        pytest.fail("dry-run must not load credentials or send requests")

    monkeypatch.setattr(rerank_experiment, "load_rerank_settings", fail)
    monkeypatch.setattr(httpx, "Client", fail)
    rerank_experiment.main(["--dataset", str(dataset), "--baseline", str(baseline),
                            "--case", "C1", "--dry-run"])
    assert not (tmp_path / "evaluation/runs").exists()


def test_changed_dataset_is_rejected_before_network(tmp_path, monkeypatch):
    dataset, baseline = prepare(tmp_path, monkeypatch)
    dataset.write_text(dataset.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rerank_experiment.main(["--dataset", str(dataset), "--baseline", str(baseline),
                                "--case", "C1", "--dry-run"])


@pytest.mark.parametrize("status", [200, 503])
def test_real_shape_is_saved_without_rewriting_baseline(tmp_path, monkeypatch, status):
    dataset, baseline = prepare(tmp_path, monkeypatch)
    original = baseline.read_bytes()
    monkeypatch.setattr(rerank_experiment, "load_rerank_settings", lambda: RerankSettings(
        "https://rerank.test/v1/rerank", "test-model", "test-secret"))

    def handler(request):
        if status != 200:
            return httpx.Response(status, json={"message": "unavailable"})
        return httpx.Response(200, json={"results": [
            {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.8}]})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    rerank_experiment.main(["--dataset", str(dataset), "--baseline", str(baseline), "--case", "C1"])
    report = json.loads(next((tmp_path / "evaluation/runs").glob("*.json")).read_text(encoding="utf-8"))
    assert report["baseline_sha256"] == hashlib.sha256(original).hexdigest()
    assert report["original_chunks"][0]["chunk_id"] == "A"
    assert report["evidence_positions"][0]["before"] == [1]
    if status == 200:
        assert report["evidence_group_coverage"]["coverage"] == 1.0
        assert report["collection"]["ranked_chunks"][0]["chunk_id"] == "B"
        assert report["evidence_positions"][0]["after"] == [2]
    else:
        assert report["evidence_group_coverage"]["status"] == "not_evaluated"
        assert report["status"] == "failed"
        assert report["collection"]["error_kind"] == "http_error"
        assert report["evidence_positions"][0]["after"] is None
        assert report["evidence_coverage"]["status"] == "not_evaluated"
    assert baseline.read_bytes() == original
    assert "test-secret" not in json.dumps(report)


def prepare_snapshot(tmp_path, monkeypatch):
    dataset, baseline = prepare(tmp_path, monkeypatch)
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    saved["records"][0].update(mode="mix", max_total_tokens_requested=40000)
    saved["started_at_utc"] = "2026-10-16T05:03:29+00:00"
    saved["records"][0]["elapsed_seconds"] = 12.0
    baseline.write_text(json.dumps(saved), encoding="utf-8")
    snapshot = tmp_path / "capture.json"
    snapshot.write_text(json.dumps({
        "schema_version": 1, "capture_boundary": "before_process_chunks_unified",
        "created_at_utc": "2026-10-16T05:03:39+00:00",
        "workspace": "test-corpus", "query": "Find alpha", "mode": "mix",
        "budget": {"total_tokens": 40000, "available_chunk_tokens": 27000},
        "chunk_top_k": 20, "enable_rerank": False,
        "merged_chunks": [
            {"chunk_id": "A", "file_path": "a.md", "content": "alpha"},
            {"chunk_id": "B", "file_path": "b.md", "content": "beta"},
            {"chunk_id": "C", "file_path": "c.md", "content": "gamma"},
        ],
    }), encoding="utf-8")
    return dataset, baseline, snapshot


def snapshot_args(dataset, baseline, snapshot):
    return ["--dataset", str(dataset), "--baseline", str(baseline), "--case", "C1",
            "--candidate-snapshot", str(snapshot), "--snapshot-sha256",
            hashlib.sha256(snapshot.read_bytes()).hexdigest()]


def test_snapshot_dry_run_uses_all_pretruncation_candidates_without_credentials(tmp_path, monkeypatch, capsys):
    dataset, baseline, snapshot = prepare_snapshot(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        pytest.fail("snapshot dry-run must not contact provider or load credentials")
    monkeypatch.setattr(rerank_experiment, "load_rerank_settings", fail)
    monkeypatch.setattr(httpx, "Client", fail)
    rerank_experiment.main(snapshot_args(dataset, baseline, snapshot) + ["--dry-run"])
    assert "Candidates: 3" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["question", "budget", "duplicate", "hash", "time", "final_not_in_candidates"])
def test_snapshot_mismatch_is_rejected_before_network(tmp_path, monkeypatch, change):
    dataset, baseline, snapshot = prepare_snapshot(tmp_path, monkeypatch)
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    if change == "question":
        data["query"] = "different question"
    elif change == "budget":
        data["budget"]["total_tokens"] = 30000
    elif change == "duplicate":
        data["merged_chunks"].append(data["merged_chunks"][0])
    elif change == "time":
        data["created_at_utc"] = "2026-10-15T05:03:39+00:00"
    elif change == "final_not_in_candidates":
        data["merged_chunks"][0]["content"] = "different evidence"
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    args = snapshot_args(dataset, baseline, snapshot)
    if change == "hash":
        args[-1] = "0" * 64
    def fail(*args, **kwargs):
        pytest.fail("invalid snapshot must be rejected before provider access")
    monkeypatch.setattr(rerank_experiment, "load_rerank_settings", fail)
    with pytest.raises(SystemExit):
        rerank_experiment.main(args + ["--dry-run"])


def test_snapshot_real_shape_sends_whole_candidate_set_and_records_provenance(tmp_path, monkeypatch):
    dataset, baseline, snapshot = prepare_snapshot(tmp_path, monkeypatch)
    before = snapshot.read_bytes()
    monkeypatch.setattr(rerank_experiment, "load_rerank_settings", lambda: RerankSettings(
        "https://rerank.test/v1/rerank", "test-model", "test-secret"))
    def handler(request):
        payload = json.loads(request.content)
        assert payload["documents"] == ["alpha", "beta", "gamma"]
        assert payload["top_n"] == 3
        return httpx.Response(200, json={"results": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.1},
        ]})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    rerank_experiment.main(snapshot_args(dataset, baseline, snapshot))
    report = json.loads(next((tmp_path / "evaluation/runs").glob("*.json")).read_text(encoding="utf-8"))
    assert report["candidate_origin"] == "pre_truncation_merge_snapshot"
    assert report["candidate_snapshot_sha256"] == hashlib.sha256(before).hexdigest()
    assert len(report["original_chunks"]) == 3
    assert report["collection"]["ranked_chunks"][0]["chunk_id"] == "C"
    assert report["captured_budget"]["total_tokens"] == 40000
    assert snapshot.read_bytes() == before


def test_later_batch_case_uses_its_own_start_time(tmp_path, monkeypatch):
    dataset, baseline, snapshot = prepare_snapshot(tmp_path, monkeypatch)
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    saved["records"][0]["started_at_utc"] = "2026-10-16T05:13:29+00:00"
    saved["records"].append({"case_id": "OTHER"})
    baseline.write_text(json.dumps(saved), encoding="utf-8")
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    data["created_at_utc"] = "2026-10-16T05:13:39+00:00"
    snapshot.write_text(json.dumps(data), encoding="utf-8")
    rerank_experiment.main(snapshot_args(dataset, baseline, snapshot) + ["--dry-run"])


def test_batch_snapshot_without_per_case_time_is_rejected(tmp_path, monkeypatch):
    dataset, baseline, snapshot = prepare_snapshot(tmp_path, monkeypatch)
    saved = json.loads(baseline.read_text(encoding="utf-8"))
    saved["records"].append({"case_id": "OTHER"})
    baseline.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(SystemExit):
        rerank_experiment.main(snapshot_args(dataset, baseline, snapshot) + ["--dry-run"])
