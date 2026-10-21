"""Collect a DocTrace baseline for human review; do not grade model answers."""

import argparse
import hashlib
import json
import time
from dataclasses import replace
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx2 as httpx
from pydantic import ValidationError

from .schemas import AskResponse, MediumAskResponse, RecordedAskResponse, Reference
from .config import ConfigurationError, load_settings
from .citation_audit import audit_citations
from .client_auth import login_evaluation_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = PROJECT_ROOT / "evaluation" / "hr_dev_v1.json"

def check_evidence_coverage(
    gold_evidence: list[dict],
    references: list[dict] | None,
) -> dict:
    result = {
        "status": "not_evaluated",
        "expected_count": len(gold_evidence),
        "matched_count": None,
        "coverage": None,
        "checks": [],
    }

    if not gold_evidence:
        result["status"] = "not_applicable"
        return result

    if references is None:
        return result

    for evidence in gold_evidence:
        found = any(
            ref["file_path"] == evidence["file_path"]
            and any(
                evidence["quote"] in chunk
                for chunk in (ref.get("content") or [])
            )
            for ref in references
        )
        result["checks"].append({
            "file_path": evidence["file_path"],
            "quote": evidence["quote"],
            "found": found,
        })

    matched = sum(check["found"] for check in result["checks"])
    result["status"] = "checked"
    result["matched_count"] = matched
    result["coverage"] = matched / len(gold_evidence)
    return result

def check_evidence_group_coverage(
    groups: list[dict],
    references: list[dict] | None,
) -> dict:
    result = {
        "status": "not_evaluated",
        "expected_count": len(groups),
        "matched_count": None,
        "coverage": None,
        "checks": [],
    }

    if not groups:
        result["status"] = "not_applicable"
        return result

    if references is None:
        return result

    for group in groups:
        alternatives = group["alternatives"]
        if not alternatives:
            raise ValueError("Evidence group has no alternatives")

        detail = check_evidence_coverage(alternatives, references)
        found = any(check["found"] for check in detail["checks"])

        result["checks"].append({
            "group_id": group["group_id"],
            "found": found,
            "alternatives": detail["checks"],
        })

    matched = sum(check["found"] for check in result["checks"])
    result["status"] = "checked"
    result["matched_count"] = matched
    result["coverage"] = matched / len(groups)
    return result

def select_cases(dataset: dict, case_id: str | None) -> list[dict]:
    cases = dataset["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Dataset must contain cases with unique IDs.")
    if case_id is None:
        return cases
    selected = [case for case in cases if case["id"] == case_id]
    if not selected:
        raise ValueError("Unknown case ID.")
    return selected


def evaluate_case(client: httpx.Client, base_url: str, case: dict, *, endpoint="/ask") -> dict:
    record = {
        "case_id": case["id"], "question": case["question"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_behavior": case["expected_behavior"],
        "required_points": case["required_points"],
        "failure_conditions": case["failure_conditions"],
        "gold_evidence": case["evidence"],
        "http_status": None, "error_kind": None, "result": None,
        "error_stage": None,
        "retrieved_chunk_count": None, "retrieved_characters": None,
        "citation_audit": {"status": "not_evaluated"},
        "review": {"answer_correct": None, "conditions_complete": None,
                   "evidence_support": None, "citation_consistent": None, "notes": ""},
    }
    started = time.perf_counter()
    try:
        response = client.post(base_url.rstrip("/") + endpoint, json={"question": case["question"]})
        record["http_status"] = response.status_code
        if response.status_code != 200:
            record["error_kind"] = "http_error"
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("detail"), dict):
                    stage = body["detail"].get("stage")
                    if stage in ("检索", "检索策略", "重排", "回答模型", "记录保存", "内部处理"):
                        record["error_stage"] = stage
                    request_id = body["detail"].get("request_id")
                    if isinstance(request_id, str) and str(UUID(request_id)) == request_id:
                        record["request_id"] = request_id
            except ValueError:
                pass
        else:
            body = response.json()
            model = (
                RecordedAskResponse
                if isinstance(body, dict) and "request_id" in body
                else MediumAskResponse
                if isinstance(body, dict) and "retrieval" in body
                else AskResponse
            )
            answer = model.model_validate(body, strict=True)
            record["result"] = answer.model_dump()
            chunks = [chunk for ref in answer.references for chunk in (ref.content or [])]
            record["retrieved_chunk_count"] = len(chunks)
            record["retrieved_characters"] = sum(len(chunk) for chunk in chunks)
    except httpx.TimeoutException:
        record["error_kind"] = "timeout"
    except httpx.RequestError:
        record["error_kind"] = "transport_error"
    except (ValueError, ValidationError):
        record["error_kind"] = "invalid_response"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    references = None
    result = record["result"]

    if result is not None:
        if result["references"] or result["llm_generated"]:
            references = result["references"]

    record["evidence_coverage"] = check_evidence_coverage(
        case["evidence"],
        references,
    )
    if "evidence_groups" in case:
        record["evidence_group_coverage"] = check_evidence_group_coverage(
            case["evidence_groups"], references
        )
    if result is not None:
        if result["llm_generated"]:
            record["citation_audit"] = {
                "status": "checked",
                **audit_citations(result["response"], result["references"]),
            }
        else:
            record["citation_audit"] = {"status": "not_applicable"}
    return record

def evaluate_retrieval_case(client, settings, case: dict, *, mode: str = "naive", max_total_tokens: int | None = None) -> dict:
    if mode not in ("naive", "mix"):
        raise ValueError("Unsupported retrieval comparison mode")
    record = {
        "case_id": case["id"],
        "question": case["question"],
        "mode": mode,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "max_total_tokens_requested": max_total_tokens,
        "http_status": None,
        "error_kind": None,
        "result": None,
        "retrieved_chunk_count": None,
        "retrieved_characters": None,
        "retrieved_entity_count": None,
        "retrieved_relationship_count": None,
    }
    references = None
    started = time.perf_counter()
    payload = {"query": case["question"], "mode": mode, "enable_rerank": False}
    if max_total_tokens is not None:
        if type(max_total_tokens) is not int or max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be a positive integer")
        payload["max_total_tokens"] = max_total_tokens
    try:
        response = client.post(
            settings.lightrag_url + "/query/data",
            headers={"X-API-Key": settings.lightrag_api_key},
            json=payload,
        )
        record["http_status"] = response.status_code

        if response.status_code != 200:
            record["error_kind"] = "http_error"
        else:
            result = response.json()
            record["result"] = result

            if not isinstance(result, dict):
                raise ValueError("Invalid retrieval response")

            if result.get("status") != "success":
                record["error_kind"] = "upstream_error"
            else:
                chunks = result["data"]["chunks"]
                if not isinstance(chunks, list):
                    raise ValueError("Invalid chunks")

                references = [
                    Reference.model_validate(
                        {
                            "reference_id": chunk["reference_id"],
                            "file_path": chunk["file_path"],
                            "content": [chunk["content"]],
                        },
                        strict=True,
                    ).model_dump()
                    for chunk in chunks
                ]
                record["retrieved_chunk_count"] = len(chunks)
                record["retrieved_characters"] = sum(len(c["content"]) for c in chunks)
                for key, field in (("entities", "retrieved_entity_count"),
                                   ("relationships", "retrieved_relationship_count")):
                    items = result["data"].get(key)
                    record[field] = len(items) if isinstance(items, list) else None

    except httpx.TimeoutException:
        record["error_kind"] = "timeout"
    except httpx.RequestError:
        record["error_kind"] = "transport_error"
    except (ValueError, KeyError, TypeError):
        record["error_kind"] = "invalid_response"

    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    record["evidence_coverage"] = check_evidence_coverage(
        case["evidence"], references
    )
    if "evidence_groups" in case:
        record["evidence_group_coverage"] = check_evidence_group_coverage(
            case["evidence_groups"], references
        )
    return record

def run_cases(
    client: httpx.Client,
    base_url: str,
    cases: list[dict],
    *,
    settings=None,
    endpoint="/ask",
    retrieval_mode="naive",
    max_total_tokens=None,
) -> Iterator[dict]:
    # Preserve failures and continue; no automatic retry.
    for case in cases:
        if settings is not None:
            yield evaluate_retrieval_case(client, settings, case, mode=retrieval_mode,
                                          max_total_tokens=max_total_tokens)
        else:
            yield evaluate_case(client, base_url, case, endpoint=endpoint)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", help="One development case ID, e.g. HR-D02")
    selection.add_argument("--all", action="store_true", help="Run all development cases")
    parser.add_argument("--dry-run", action="store_true", help="List cases without HTTP requests")
    parser.add_argument("--endpoint", choices=("/ask", "/ask/optimized"), default="/ask")
    parser.add_argument("--login-user", help="DocTrace account; password is prompted securely, not passed in arguments")
    parser.add_argument("--mode", choices=("naive", "mix"),
                        help="Retrieval-only comparison mode; default remains naive")
    parser.add_argument("--max-total-tokens", type=int,
                        help="Positive per-request LightRAG token budget; retrieval-only, default unchanged")
    parser.add_argument(
        "--lightrag-url", choices=("http://127.0.0.1:9622", "http://127.0.0.1:9623", "http://127.0.0.1:9624"),
        help="Explicit local HR knowledge-base target; retrieval-only, without changing .env",
    )
    parser.add_argument(
    "--dataset",
    type=Path,
    default=DATASET_PATH,
    help="Path to the evaluation dataset",
)
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Evaluate retrieval without answer generation",
    )
    args = parser.parse_args(argv)
    if args.mode is not None and not args.retrieval_only:
        parser.error("--mode is only supported with --retrieval-only.")
    if args.lightrag_url is not None and not args.retrieval_only:
        parser.error("--lightrag-url is only supported with --retrieval-only.")
    if args.max_total_tokens is not None:
        if not args.retrieval_only:
            parser.error("--max-total-tokens is only supported with --retrieval-only.")
        if args.max_total_tokens <= 0:
            parser.error("--max-total-tokens must be a positive integer.")
    retrieval_mode = args.mode or "naive"
    if args.retrieval_only and args.endpoint != "/ask":
        parser.error("--retrieval-only cannot be combined with an answer endpoint selection.")
    dataset_bytes = args.dataset.read_bytes()
    dataset = json.loads(dataset_bytes.decode("utf-8"))
    if dataset.get("retrieval_only") and not args.retrieval_only:
        parser.error("This dataset is currently reviewed for retrieval-only evaluation.")
    expected_endpoint = dataset.get("expected_endpoint")
    if not args.retrieval_only and expected_endpoint and args.endpoint != expected_endpoint:
        parser.error("This dataset requires --endpoint " + expected_endpoint)
    expected_target = dataset.get("expected_retrieval_url")
    if args.retrieval_only and expected_target and args.lightrag_url != expected_target:
        parser.error("This dataset requires explicit --lightrag-url " + expected_target)
    try:
        cases = select_cases(dataset, args.case)
    except ValueError as error:
        parser.error(str(error))
    print("Dataset:", dataset["dataset_id"])
    print("Selected cases:", len(cases))
    if args.retrieval_only:
        print("Retrieval mode:", retrieval_mode)
        if args.max_total_tokens is not None:
            print("Max total tokens requested:", args.max_total_tokens)
        if args.lightrag_url:
            print("Retrieval target:", args.lightrag_url)
    if args.dry_run:
        for case in cases:
            print(case["id"], case["type"], case["expected_behavior"])
        return

    if not args.retrieval_only and not args.login_user:
        parser.error("End-to-end evaluation requires --login-user; the password is prompted securely.")

    corpus_manifest = PROJECT_ROOT / dataset["corpus_manifest"]
    corpus_bytes = corpus_manifest.read_bytes()
    corpus = json.loads(corpus_bytes.decode("utf-8"))
    hashes = {}
    for doc in corpus["documents"]:
        data = (corpus_manifest.parent / doc["cleaned_file"]).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != doc["cleaned_sha256"]:
            parser.error("Corpus hash mismatch; rebuild evaluation evidence before running.")
        hashes[doc["document_id"]] = actual
    settings = None
    if args.retrieval_only:
        try:
            settings = load_settings()
            if args.lightrag_url:
                settings = replace(settings, lightrag_url=args.lightrag_url)
        except ConfigurationError as error:
            parser.error(str(error))

    base_url = (
        settings.lightrag_url
        if settings is not None
        else "http://127.0.0.1:8001"
    )
    endpoint = "/query/data" if args.retrieval_only else args.endpoint
    evaluation_kind = (
        "retrieval_only" if args.retrieval_only
        else "optimized_end_to_end" if endpoint == "/ask/optimized" else "end_to_end"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output = PROJECT_ROOT / "evaluation" / "runs" / (run_id + ".json")
    output.parent.mkdir(exist_ok=True)
    request_options = {"mode": retrieval_mode, "enable_rerank": False} if args.retrieval_only else None
    if request_options is not None and args.max_total_tokens is not None:
        request_options["max_total_tokens"] = args.max_total_tokens
    report = {
        "run_id": run_id, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_id": dataset["dataset_id"], "split": dataset["split"],
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_scope": dataset.get("scope"),
        "dataset_review_file": dataset.get("review_file"),
        "expected_retrieval_url": dataset.get("expected_retrieval_url"),
        "corpus_id": dataset["corpus_id"], "corpus_sha256_by_document": hashes,
        "evaluation_kind": evaluation_kind,
        "base_url": base_url,
        "endpoint": endpoint,
        "mode_expected": retrieval_mode if args.retrieval_only else dataset.get("expected_mode"),
        "actual_server_configuration": "not independently inspected",
        "request_options": request_options,
        "evaluation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evidence_metric_scope": ("Exact source quotes in returned chunks; graph descriptions are not scored as chunk coverage."
                                  if args.retrieval_only else None),
        "cache_state": "unknown; no cache cleared", "status": "running", "records": [],
    }
    timeout = httpx.Timeout(150.0, connect=5.0, write=10.0, pool=5.0)
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
        if not args.retrieval_only:
            try:
                login_evaluation_client(client, base_url, args.login_user)
            except ConfigurationError as error:
                parser.error(str(error))
        for record in run_cases(
            client, report["base_url"], cases, settings=settings, endpoint=endpoint,
            retrieval_mode=retrieval_mode,
            max_total_tokens=args.max_total_tokens,
        ):
            report["records"].append(record)
            # Write after every question so an interrupted batch preserves finished cases.
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(record["case_id"], "HTTP:", record["http_status"], "error:", record["error_kind"],
                  "seconds:", record["elapsed_seconds"], flush=True)
    report["status"] = "completed_unscored"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report:", output)


if __name__ == "__main__":
    main()
