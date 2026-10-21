"""Rerank one fixed baseline candidate set; preserve all candidates and raw results."""

import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx

from .config import ConfigurationError
from .evaluate import check_evidence_coverage, check_evidence_group_coverage, select_cases
from .rerank_client import collect_rerank
from .rerank_config import load_rerank_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = Path(__file__).resolve().parent


def validate_candidate_snapshot(snapshot_bytes, expected_sha256, baseline, saved):
    """Keep a pre-limit snapshot distinct from a final retrieval response."""
    if hashlib.sha256(snapshot_bytes).hexdigest() != expected_sha256:
        raise ValueError("Candidate snapshot hash mismatch")
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    if (snapshot["schema_version"] != 1
            or snapshot["capture_boundary"] != "before_process_chunks_unified"
            or snapshot["workspace"] != baseline["corpus_id"]
            or snapshot["query"] != saved["question"]
            or snapshot["mode"] != saved["mode"]
            or snapshot["enable_rerank"] is not False
            or snapshot["budget"]["total_tokens"] != saved["max_total_tokens_requested"]):
        raise ValueError("Candidate snapshot request mismatch")
    captured = datetime.fromisoformat(snapshot["created_at_utc"])
    if "started_at_utc" in saved:
        started = datetime.fromisoformat(saved["started_at_utc"])
    elif len(baseline["records"]) == 1:
        started = datetime.fromisoformat(baseline["started_at_utc"])
    else:
        raise ValueError("Batch snapshots require a per-case start timestamp")
    if captured.tzinfo is None or started.tzinfo is None:
        raise ValueError("Snapshot timestamps need timezone")
    if not started <= captured <= started + timedelta(seconds=saved["elapsed_seconds"] + 1):
        raise ValueError("Snapshot is outside selected run")
    chunks = snapshot["merged_chunks"]
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("Empty snapshot candidates")
    for chunk in chunks:
        if not isinstance(chunk, dict) or any(
                not isinstance(chunk.get(k), str) or not chunk[k]
                for k in ("chunk_id", "file_path", "content")):
            raise ValueError("Invalid snapshot candidate")
    if len({c["chunk_id"] for c in chunks}) != len(chunks):
        raise ValueError("Duplicate snapshot candidates")
    identity = lambda c: (c["chunk_id"], c["file_path"], c["content"])
    final = saved["result"]["data"]["chunks"]
    if [identity(c) for c in chunks[:len(final)]] != [identity(c) for c in final]:
        raise ValueError("Snapshot prefix differs from actual unreranked result")
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--candidate-snapshot", type=Path,
                        help="Explicit pre-truncation diagnostic snapshot linked to baseline")
    parser.add_argument("--snapshot-sha256",
                        help="SHA256 verified against the capture log; required with snapshot")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.candidate_snapshot) != bool(args.snapshot_sha256):
        parser.error("--candidate-snapshot and --snapshot-sha256 must be used together.")
    snapshot = None
    try:
        baseline_bytes = args.baseline.read_bytes()
        dataset_bytes = args.dataset.read_bytes()
        baseline = json.loads(baseline_bytes.decode("utf-8"))
        dataset = json.loads(dataset_bytes.decode("utf-8"))
        if (baseline["evaluation_kind"] != "retrieval_only"
                or baseline["dataset_sha256"] != hashlib.sha256(dataset_bytes).hexdigest()
                or baseline["dataset_id"] != dataset["dataset_id"]
                or baseline["corpus_id"] != dataset["corpus_id"]):
            raise ValueError("Baseline and dataset versions do not match.")
        case = select_cases(dataset, args.case)[0]
        records = [r for r in baseline["records"] if r["case_id"] == case["id"]]
        if len(records) != 1:
            raise ValueError("Baseline must contain exactly one matching record.")
        saved = records[0]
        if (saved["question"] != case["question"] or saved["http_status"] != 200
                or saved["error_kind"] is not None or saved["result"]["status"] != "success"):
            raise ValueError("Baseline case did not complete retrieval successfully.")
        chunks = saved["result"]["data"]["chunks"]
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("Baseline must contain nonempty candidate chunks.")
        for chunk in chunks:
            if not isinstance(chunk, dict) or any(
                not isinstance(chunk.get(key), str) or not chunk[key]
                for key in ("chunk_id", "reference_id", "file_path", "content")
            ):
                raise ValueError("Invalid baseline chunk.")
        if len({c["chunk_id"] for c in chunks}) != len(chunks):
            raise ValueError("Baseline contains duplicate chunk IDs.")
        if args.candidate_snapshot:
            snapshot = validate_candidate_snapshot(
                args.candidate_snapshot.read_bytes(), args.snapshot_sha256, baseline, saved
            )
            chunks = snapshot["merged_chunks"]
        manifest = PROJECT_ROOT / dataset["corpus_manifest"]
        documents = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
        current_hashes = {}
        for doc in documents:
            actual = hashlib.sha256((manifest.parent / doc["cleaned_file"]).read_bytes()).hexdigest()
            if actual != doc["cleaned_sha256"]:
                raise ValueError("Corpus content has changed.")
            current_hashes[doc["document_id"]] = actual
        if current_hashes != baseline["corpus_sha256_by_document"]:
            raise ValueError("Corpus does not match baseline.")
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Cannot validate baseline, selected case, dataset or corpus; check their versions and structure.")

    print("Dataset:", dataset["dataset_id"])
    print("Case:", case["id"])
    print("Candidates:", len(chunks))
    print("Characters:", sum(len(c["content"]) for c in chunks))
    if args.dry_run:
        print("Dry run: no provider request sent.")
        return
    try:
        settings = load_rerank_settings()
    except ConfigurationError as error:
        parser.error(str(error))

    started_at = datetime.now(timezone.utc).isoformat()
    timeout = httpx.Timeout(120.0, connect=5.0, write=30.0, pool=5.0)
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        collection = collect_rerank(client, settings, case["question"], chunks)
    ranked = collection["ranked_chunks"]
    positions = []
    for evidence in case["evidence"]:
        def find_positions(candidate_list):
            if candidate_list is None:
                return None
            return [i for i, chunk in enumerate(candidate_list, 1)
                    if chunk["file_path"] == evidence["file_path"]
                    and evidence["quote"] in chunk["content"]]
        positions.append({"file_path": evidence["file_path"], "quote": evidence["quote"],
                          "before": find_positions(chunks), "after": find_positions(ranked)})
    references = None if ranked is None else [
        {"file_path": c["file_path"], "content": [c["content"]]} for c in ranked]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    report = {
        "run_id": run_id, "started_at_utc": started_at,
        "evaluation_kind": "fixed_candidates_rerank", "case_id": case["id"],
        "question": case["question"], "dataset_id": dataset["dataset_id"],
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "baseline_run_id": baseline["run_id"],
        "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
        "corpus_id": dataset["corpus_id"], "corpus_sha256_by_document": current_hashes,
        "source_sha256": {name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest()
                          for name in ("rerank.py", "rerank_client.py", "rerank_experiment.py", "evaluate.py")},
        "provider_url": settings.rerank_url, "model": settings.rerank_model,
        "request_options": {"top_n": len(chunks), "return_documents": False},
        "provider_other_options": "service defaults; not independently inspected",
        "original_chunks": chunks, "collection": collection,
        "evidence_positions": positions,
        "evidence_coverage": check_evidence_coverage(case["evidence"], references),
        "status": "completed_unscored" if collection["error_kind"] is None else "failed",
        "notes": "No new retrieval, filtering, answer generation or index changes. Full-list coverage does not establish ranking improvement.",
    }
    if snapshot is not None:
        report.update(
            candidate_origin="pre_truncation_merge_snapshot",
            candidate_snapshot_sha256=args.snapshot_sha256,
            candidate_snapshot_file=str(args.candidate_snapshot),
            capture_id=snapshot.get("capture_id"),
            captured_budget=snapshot["budget"],
            captured_chunk_top_k=snapshot["chunk_top_k"],
            captured_tokenizer_model_name=snapshot.get("tokenizer_model_name"),
        )
    if "evidence_groups" in case:
        report["evidence_group_coverage"] = check_evidence_group_coverage(
            case["evidence_groups"], references
        )
    output = PROJECT_ROOT / "evaluation" / "runs" / (run_id + "_rerank.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    print("HTTP:", collection["http_status"], "error:", collection["error_kind"],
          "seconds:", collection["elapsed_seconds"])
    for evidence in positions:
        print("Evidence:", evidence["file_path"], evidence["before"], "->", evidence["after"])
    print("Report:", output)


if __name__ == "__main__":
    main()
