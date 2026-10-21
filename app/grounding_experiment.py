"""Review one saved optimized answer, without retrieval or answer regeneration."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx

from .answer_config import load_answer_settings
from .config import ConfigurationError
from .grounding_client import collect_grounding_review
from .grounding_prompt import build_grounding_messages
from .review_evidence import select_cited_references
from .review_units import build_item_review_windows
from .schemas import AskResponse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "runs"


def load_saved_answer(source: Path, case_id: str) -> tuple[dict, dict, dict, str]:
    source_bytes = source.read_bytes()
    saved = json.loads(source_bytes.decode("utf-8"))
    if saved["evaluation_kind"] != "optimized_end_to_end":
        raise ValueError("Expected an optimized answer run")
    matches = [r for r in saved["records"] if r["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("Expected one matching saved record")
    record = matches[0]
    if record["http_status"] != 200 or record["error_kind"] is not None:
        raise ValueError("Saved answer did not succeed")
    result = AskResponse.model_validate(record["result"], strict=True).model_dump()
    if not result["llm_generated"] or not result["response"].strip():
        raise ValueError("Expected a nonempty model-generated answer")
    if not isinstance(record["question"], str) or not record["question"].strip():
        raise ValueError("Missing saved question")
    refs = result["references"]
    if not refs or len({r["reference_id"] for r in refs}) != len(refs):
        raise ValueError("Missing or duplicate references")
    for ref in refs:
        if (not ref["reference_id"].strip() or not ref["file_path"].strip()
                or not ref["content"] or any(not c.strip() for c in ref["content"])):
            raise ValueError("Missing selected evidence content")
    return saved, record, result, hashlib.sha256(source_bytes).hexdigest()


def load_focus(path: Path, source_hash: str, run_id: str, case_id: str, answer: dict) -> tuple[str, list[dict], dict]:
    """Select exact saved spans; never rewrite or attach a desired review label."""
    raw = path.read_bytes()
    focus = json.loads(raw.decode("utf-8"))
    fields = {"source_run_id", "source_sha256", "case_id", "answer_quote", "reference_id", "evidence_quote"}
    if (not isinstance(focus, dict) or set(focus) != fields
            or not all(isinstance(v, str) and v.strip() for v in focus.values())):
        raise ValueError("Invalid focus selection fields")
    if (focus["source_sha256"] != source_hash or focus["source_run_id"] != run_id
            or focus["case_id"] != case_id):
        raise ValueError("Focus selection does not match saved source")
    answer_start = answer["response"].find(focus["answer_quote"])
    if answer_start < 0:
        raise ValueError("Focused answer quote is not in saved answer")
    ref = next((r for r in answer["references"] if r["reference_id"] == focus["reference_id"]), None)
    if ref is None:
        raise ValueError("Unknown focused reference")
    match = next(((i, content.find(focus["evidence_quote"]))
                  for i, content in enumerate(ref["content"])
                  if focus["evidence_quote"] in content), None)
    if match is None:
        raise ValueError("Focused evidence is not in a single saved source chunk")
    index, evidence_start = match
    selected = [{"reference_id": ref["reference_id"], "file_path": ref["file_path"],
                 "content": [focus["evidence_quote"]]}]
    metadata = {
        "file": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
        "reference_id": ref["reference_id"], "source_content_index": index,
        "answer_start": answer_start, "answer_end": answer_start + len(focus["answer_quote"]),
        "evidence_start": evidence_start, "evidence_end": evidence_start + len(focus["evidence_quote"]),
        "selection_method": "manual exact excerpts; zero-based character offsets; end exclusive",
    }
    return focus["answer_quote"], selected, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--case", required=True)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--focus", type=Path, help="Optional source-bound exact excerpt selection JSON")
    scope.add_argument("--target", help="One automatically split target ID, e.g. 4.3")
    parser.add_argument("--neighbors", type=int, help="Explicit neighboring paragraph count for --target")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if (args.target is not None) != (args.neighbors is not None):
        parser.error("--target and --neighbors must be provided together.")
    try:
        saved, record, answer, source_hash = load_saved_answer(args.source, args.case)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Cannot validate source run or selected saved model answer.")
    question, text, refs = record["question"], answer["response"], answer["references"]
    focus_metadata = None
    target_metadata = None
    review_window = None
    if args.focus is not None:
        try:
            text, refs, focus_metadata = load_focus(args.focus, source_hash, saved["run_id"], args.case, answer)
        except (OSError, ValueError, KeyError, TypeError):
            parser.error("Cannot validate focused excerpts against the saved source.")
    if args.target is not None:
        try:
            windows = build_item_review_windows(text, neighbor_count=args.neighbors)
            matches = [w for w in windows
                       if f"{w['target']['unit_id']}.{w['target']['item_id']}" == args.target]
            if len(matches) != 1:
                raise ValueError("Unknown target")
            review_window = matches[0]
            text = review_window["target"]["text"]
            selection = select_cited_references(text, refs)
            refs = selection["references"]
            target_metadata = {"target_id": args.target, "neighbor_count": args.neighbors,
                               "selection_policy": selection["selection_policy"],
                               "citation_audit": selection["citation_audit"]}
        except (ValueError, KeyError, TypeError):
            parser.error("Cannot select target or its known cited references.")
    review_scope = ("list_item_target" if review_window is not None else
                    "focused_excerpts" if focus_metadata is not None else "full_saved_answer")
    messages = build_grounding_messages(question, text, refs, review_window=review_window)
    print("Source run:", saved["run_id"])
    print("Case:", args.case)
    print("Scope:", review_scope)
    if target_metadata is not None:
        print("Target:", args.target)
        print("Cited references:", target_metadata["citation_audit"]["cited_ids"])
    print("Evidence chunks:", sum(len(r["content"]) for r in refs))
    print("Evidence characters:", sum(len(c) for r in refs for c in r["content"]))
    if args.dry_run:
        print("Dry run: no provider request sent.")
        return
    try:
        settings = load_answer_settings()
    except ConfigurationError as error:
        parser.error(str(error))

    started_at = datetime.now(timezone.utc).isoformat()
    timeout = httpx.Timeout(120.0, connect=5.0, write=30.0, pool=5.0)
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        collection = collect_grounding_review(client, settings, question, text, refs, review_window=review_window)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    source_files = ("grounding_review.py", "grounding_prompt.py", "grounding_client.py",
                    "grounding_experiment.py", "answer_config.py", "schemas.py",
                    "review_units.py", "review_evidence.py", "citation_audit.py")
    report = {
        "run_id": run_id, "started_at_utc": started_at,
        "evaluation_kind": ("target_saved_answer_grounding_review" if review_window is not None else
                            "focused_saved_answer_grounding_review" if focus_metadata is not None else "saved_answer_grounding_review"),
        "review_scope": review_scope,
        "target_selection": target_metadata, "review_window": review_window,
        "focus_selection": focus_metadata, "case_id": args.case,
        "source_run_id": saved["run_id"], "source_file": str(args.source.resolve()),
        "source_sha256": source_hash, "source_dataset_id": saved.get("dataset_id"),
        "source_dataset_sha256": saved.get("dataset_sha256"),
        "review_input": json.loads(messages[1]["content"]),
        "messages": messages,
        "provider_url": settings.answer_url, "model": settings.answer_model,
        "request_options": {"stream": False, "thinking": {"type": "disabled"}},
        "source_sha256_by_file": {name: hashlib.sha256(
            (PROJECT_ROOT / "app" / name).read_bytes()).hexdigest() for name in source_files},
        "collection": collection,
        "status": "completed_unscored" if collection["error_kind"] is None else "failed",
        "manual_review": {"findings_correct": None, "missed_issues": None, "notes": ""},
        "limitations": [
            "Anchor validity does not establish semantic correctness or complete issue detection.",
            "Review uses the configured answering-model service; shared blind spots are possible.",
            "Only saved evidence is reviewed; no new retrieval, answer regeneration, auto-repair or retry.",
            "Source run has grouped evidence; original global chunk order and chunk IDs are unavailable.",
        ],
    }
    if focus_metadata is not None:
        report["limitations"].append(
            "Manual diagnostic excerpt selection changes both answer and evidence scope; "
            "it is not automatic chunk selection, retrieval improvement or whole-answer verification. "
            "A single comparison cannot isolate the cause of a missed issue."
        )
    if review_window is not None:
        report["limitations"].append(
            "Only target-cited sources are included. Citation IDs can be wrong and uncited "
            "cross-document conditions may be missed. Original source chunks are not shortened. "
            "Target/context packaging, system instructions and evidence scope differ from earlier modes; "
            "a result cannot isolate the effect of one change. Titles/intros without known citations "
            "are not sent by this target-selection path."
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{run_id}_grounding.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    result = collection["result"]
    print("HTTP:", collection["http_status"], "error:", collection["error_kind"])
    print("Review:", result["status"] if result is not None else "not_evaluated")
    print("Findings:", len(result["findings"]) if result is not None else None)
    print("Report:", path)


if __name__ == "__main__":
    main()
