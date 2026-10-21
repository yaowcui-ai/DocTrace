"""Offline equal-budget selection comparison; never contacts model services."""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .context_selection import select_context
from .evaluate import check_evidence_coverage, check_evidence_group_coverage


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = Path(__file__).resolve().parent


def measure(case: dict, chunks: list[dict], max_chars: int, min_score=None) -> dict:
    selection = select_context(chunks, max_chars=max_chars, min_score=min_score)
    refs = [{"file_path": c["file_path"], "content": [c["content"]]}
            for c in selection["selected_chunks"]]
    return {
        **selection,
        "input_chunk_count": len(chunks),
        "input_characters": sum(len(c["content"]) for c in chunks),
        "selected_chunk_count": len(selection["selected_chunks"]),
        "evidence_coverage": check_evidence_coverage(case["evidence"], refs),
        "evidence_group_coverage": check_evidence_group_coverage(case["evidence_groups"], refs),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--max-chars", type=int, required=True)
    parser.add_argument("--min-score", type=float, default=None)
    args = parser.parse_args(argv)
    if args.max_chars <= 0:
        parser.error("--max-chars must be positive.")
    if args.min_score is not None and not math.isfinite(args.min_score):
        parser.error("--min-score must be finite.")
    inputs = []
    try:
        dataset_bytes = args.dataset.read_bytes()
        batch_bytes = args.batch.read_bytes()
        dataset = json.loads(dataset_bytes.decode("utf-8"))
        batch = json.loads(batch_bytes.decode("utf-8"))
        if (batch["annotation_dataset"] != dataset["dataset_id"]
                or batch["annotation_dataset_sha256"] != hashlib.sha256(dataset_bytes).hexdigest()):
            raise ValueError("Annotation dataset mismatch")
        cases = {case["id"]: case for case in dataset["cases"]}
        if len(cases) != len(dataset["cases"]):
            raise ValueError("Duplicate case IDs")
        manifest_path = PROJECT_ROOT / dataset["corpus_manifest"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        corpus_hashes = {}
        for doc in manifest["documents"]:
            actual = hashlib.sha256((manifest_path.parent / doc["cleaned_file"]).read_bytes()).hexdigest()
            if actual != doc["cleaned_sha256"]:
                raise ValueError("Corpus changed")
            corpus_hashes[doc["document_id"]] = actual
        if not batch["records"] or len({x["case_id"] for x in batch["records"]}) != len(batch["records"]):
            raise ValueError("Invalid source batch")
        for entry in batch["records"]:
            name = entry["source_report"]
            if Path(name).name != name:
                raise ValueError("Source must be a filename in evaluation/runs")
            raw = (PROJECT_ROOT / "evaluation/runs" / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["source_sha256"]:
                raise ValueError("Source changed")
            saved = json.loads(raw.decode("utf-8"))
            case = cases[entry["case_id"]]
            if (saved["case_id"] != case["id"] or saved["question"] != case["question"]
                    or saved["evaluation_kind"] != "fixed_candidates_rerank"
                    or saved["corpus_id"] != dataset["corpus_id"]
                    or saved["corpus_sha256_by_document"] != corpus_hashes
                    or saved["collection"]["error_kind"] is not None):
                raise ValueError("Source and annotation inputs do not match")
            original = saved["original_chunks"]
            ranked = saved["collection"]["ranked_chunks"]
            def chunk_map(chunks):
                return {c["chunk_id"]: (c["file_path"], c["content"], c["reference_id"])
                        for c in chunks}
            if (len(chunk_map(original)) != len(original) or len(original) != len(ranked)
                    or chunk_map(original) != chunk_map(ranked)):
                raise ValueError("Candidate identity or content changed")
            inputs.append((entry, case, original, ranked))
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Cannot validate source reports, annotations or corpus; check versions and structure.")

    records = []
    for entry, case, original, ranked in inputs:
        record = {
            "case_id": case["id"], "source_report": entry["source_report"],
            "source_sha256": entry["source_sha256"],
            "original": measure(case, original, args.max_chars),
            "reranked": measure(case, ranked, args.max_chars),
        }
        if args.min_score is not None:
            record["reranked_filtered"] = measure(case, ranked, args.max_chars, args.min_score)
        records.append(record)
    summary = {}
    variants = ["original", "reranked"]
    if args.min_score is not None:
        variants.append("reranked_filtered")
    for order in variants:
        metrics = [row[order] for row in records]
        eligible = [x for x in metrics if x["evidence_group_coverage"]["expected_count"] > 0]
        before = sum(x["input_characters"] for x in metrics)
        after = sum(x["characters"] for x in metrics)
        summary[order] = {
            "cases": len(records), "eligible_cases": len(eligible),
            "complete_cases": sum(x["evidence_group_coverage"]["coverage"] == 1.0 for x in eligible),
            "matched_groups": sum(x["evidence_group_coverage"]["matched_count"] for x in eligible),
            "expected_groups": sum(x["evidence_group_coverage"]["expected_count"] for x in eligible),
            "input_characters": before, "selected_characters": after,
            "character_reduction_fraction": 1 - after / before if before else None,
        }
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    report = {
        "run_id": run_id, "evaluation_kind": "offline_equal_budget_selection",
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "batch_sha256": hashlib.sha256(batch_bytes).hexdigest(),
        "corpus_sha256_by_document": corpus_hashes,
        "source_sha256": {name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest()
                          for name in ("context_selection.py", "context_experiment.py", "evaluate.py")},
        "max_chars": args.max_chars, "min_score": args.min_score, "network_calls": 0,
        "summary": summary, "records": records,
        "limits": [
            "Development-set offline analysis using retrospectively refined v3 annotations.",
            "Character counts cover selected raw chunks, not total prompt tokens or measured model cost.",
            "No answer generation, online deployment or new provider requests.",
            "No-gold wage case is not included in evidence-coverage denominators.",
            "Original failed provider attempts remain in their source history; this analysis uses completed rankings.",
        ],
    }
    output = PROJECT_ROOT / "evaluation/runs" / (run_id + "_context.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    for order, values in summary.items():
        print(order, "complete cases:", f"{values['complete_cases']}/{values['eligible_cases']}",
              "groups:", f"{values['matched_groups']}/{values['expected_groups']}",
              "characters:", values["selected_characters"])
    print("Report:", output)


if __name__ == "__main__":
    main()
