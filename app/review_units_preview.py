"""Prepare traceable answer-context windows from a saved run, without networking."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .grounding_experiment import load_saved_answer
from .review_units import build_item_review_windows, build_review_windows


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "runs"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--neighbors", type=int, required=True,
                        help="Number of neighboring answer paragraphs on each side")
    parser.add_argument("--split-lists", action="store_true",
                        help="Refine top-level list items and retain intro and parent context")
    args = parser.parse_args(argv)
    try:
        saved, record, answer, source_hash = load_saved_answer(args.source, args.case)
        build_windows = build_item_review_windows if args.split_lists else build_review_windows
        windows = build_windows(answer["response"], neighbor_count=args.neighbors)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Cannot validate saved answer or nonnegative neighbor count.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    code_files = ("review_units.py", "review_units_preview.py", "grounding_experiment.py", "schemas.py")
    report = {
        "run_id": run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_kind": "offline_review_window_preview", "status": "prepared_unreviewed",
        "source_run_id": saved["run_id"], "source_file": str(args.source.resolve()),
        "source_sha256": source_hash, "case_id": args.case,
        "source_dataset_id": saved.get("dataset_id"),
        "source_dataset_sha256": saved.get("dataset_sha256"),
        "question": record["question"], "source_answer": answer["response"],
        "neighbor_count": args.neighbors, "windows": windows,
        "segmentation": "top_level_list_items" if args.split_lists else "paragraphs",
        "references": answer["references"],
        "source_sha256_by_file": {name: hashlib.sha256(
            (PROJECT_ROOT / "app" / name).read_bytes()).hexdigest() for name in code_files},
        "limitations": [
            "No credentials loaded and no provider, retrieval or answering requests sent.",
            "Paragraph windows are not independent semantic claims. Titles remain as targets.",
            "Fixed neighbors may miss distant conditions, headings or cross-section exceptions.",
            "All original references are retained for inspection; no automatic evidence selection.",
            "Structural targets may still contain several claims; do not infer whole-answer verification.",
        ],
    }
    if args.split_lists:
        report["limitations"].append(
            "Only unindented top-level list markers are refined; nested content remains with its item. "
            "Fenced answers disable refinement. Intros and headings remain structural targets. "
            "Full parent context preserves sibling text but does not guarantee all distant conditions."
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{run_id}_units.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    print("Source run:", saved["run_id"])
    print("Case:", args.case)
    print("Neighbors per side:", args.neighbors)
    print("Segmentation:", report["segmentation"])
    print("Targets:", len(windows))
    for window in windows:
        target = window["target"]
        label = f"{target['unit_id']}.{target['item_id']}" if "item_id" in target else target["unit_id"]
        print("Target:", label, "characters:", len(target["text"]),
              "before:", [p["unit_id"] for p in window["context_before"]],
              "after:", [p["unit_id"] for p in window["context_after"]])
    print("No model request sent.")
    print("Report:", path)


if __name__ == "__main__":
    main()
