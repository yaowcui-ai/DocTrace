import hashlib
import json

import httpx2 as httpx
import pytest

from app import context_experiment


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(context_experiment, "PROJECT_ROOT", tmp_path)
    (tmp_path / "evaluation/runs").mkdir(parents=True)
    (tmp_path / "corpus.json").write_text('{"documents": []}', encoding="utf-8")
    case = {"id": "C1", "question": "Find alpha", "evidence": [
        {"file_path": "a.md", "quote": "aaaa"}], "evidence_groups": [
            {"group_id": "alpha", "alternatives": [{"file_path": "a.md", "quote": "aaaa"}]}]}
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"dataset_id": "v3", "corpus_id": "corpus",
        "corpus_manifest": "corpus.json", "cases": [case]}), encoding="utf-8")
    chunks = [{"chunk_id": "A", "file_path": "a.md", "reference_id": "1", "content": "aaaa"},
              {"chunk_id": "B", "file_path": "b.md", "reference_id": "2", "content": "bbbbb"}]
    source = tmp_path / "evaluation/runs/source.json"
    source.write_text(json.dumps({"case_id": "C1", "question": "Find alpha",
        "evaluation_kind": "fixed_candidates_rerank", "corpus_id": "corpus",
        "corpus_sha256_by_document": {}, "original_chunks": chunks,
        "collection": {"error_kind": None, "ranked_chunks": [
            {**chunks[1], "rerank_score": 0.9}, {**chunks[0], "rerank_score": 0.1}]}}), encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"annotation_dataset": "v3",
        "annotation_dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "records": [{"case_id": "C1", "source_report": source.name,
                     "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}), encoding="utf-8")
    return dataset, batch, source


def test_offline_comparison_uses_equal_budget_and_preserves_sources(tmp_path, monkeypatch):
    dataset, batch, source = prepare(tmp_path, monkeypatch)
    before = source.read_bytes()

    def fail(*args, **kwargs):
        pytest.fail("Offline selection must not create an HTTP client")

    monkeypatch.setattr(httpx, "Client", fail)
    context_experiment.main(["--dataset", str(dataset), "--batch", str(batch), "--max-chars", "5"])
    output = next((tmp_path / "evaluation/runs").glob("*_context.json"))
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["max_chars"] == 5
    assert report["network_calls"] == 0
    record = report["records"][0]
    assert record["original"]["evidence_group_coverage"]["coverage"] == 1.0
    assert record["reranked"]["evidence_group_coverage"]["coverage"] == 0.0
    assert record["original"]["characters"] <= 5
    assert record["reranked"]["characters"] <= 5
    assert source.read_bytes() == before


def test_changed_source_is_rejected(tmp_path, monkeypatch):
    dataset, batch, source = prepare(tmp_path, monkeypatch)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        context_experiment.main(["--dataset", str(dataset), "--batch", str(batch), "--max-chars", "5"])
    assert not list((tmp_path / "evaluation/runs").glob("*_context.json"))


def test_invalid_budget_is_rejected_before_output(tmp_path, monkeypatch):
    dataset, batch, source = prepare(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        context_experiment.main(["--dataset", str(dataset), "--batch", str(batch), "--max-chars", "0"])


def test_threshold_adds_separate_variant_and_preserves_budget_only_control(tmp_path, monkeypatch):
    dataset, batch, source = prepare(tmp_path, monkeypatch)
    context_experiment.main(["--dataset", str(dataset), "--batch", str(batch),
                             "--max-chars", "10", "--min-score", "0.3"])
    output = next((tmp_path / "evaluation/runs").glob("*_context.json"))
    report = json.loads(output.read_text(encoding="utf-8"))
    row = report["records"][0]
    assert report["min_score"] == 0.3
    assert row["reranked"]["selected_chunk_count"] == 2
    assert row["reranked"]["evidence_group_coverage"]["coverage"] == 1.0
    assert row["reranked_filtered"]["selected_chunk_count"] == 1
    assert row["reranked_filtered"]["evidence_group_coverage"]["coverage"] == 0.0
    assert row["reranked_filtered"]["decisions"][1]["reason"] == "below_min_score"
    assert report["summary"]["reranked_filtered"]["matched_groups"] == 0


@pytest.mark.parametrize("score", ["nan", "inf"])
def test_nonfinite_threshold_is_rejected(tmp_path, monkeypatch, capsys, score):
    dataset, batch, source = prepare(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        context_experiment.main(["--dataset", str(dataset), "--batch", str(batch),
                                 "--max-chars", "10", "--min-score", score])
    assert "--min-score must be finite" in capsys.readouterr().err
