"""Retrieve candidate chunks without involving evaluation datasets or answer generation."""

import json
import time

import httpx2 as httpx

from .config import Settings


def collect_retrieval(
    client,
    settings: Settings,
    question: str,
    *,
    mode: str = "naive",
    max_total_tokens: int | None = None,
) -> dict:
    if mode not in ("naive", "mix"):
        raise ValueError("mode must be naive or mix")

    if max_total_tokens is not None:
        if type(max_total_tokens) is not int or max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be a positive integer")

    payload = {
        "query": question,
        "mode": mode,
        "enable_rerank": False,
    }

    if max_total_tokens is not None:
        payload["max_total_tokens"] = max_total_tokens
    record = {
        "http_status": None, "error_kind": None, "raw_response": None,
        "chunks": None, "policy_metadata": None,
    }
    started = time.perf_counter()
    try:
        response = client.post(
            settings.lightrag_url + "/query/data",
            headers={"X-API-Key": settings.lightrag_api_key},
            json=payload,
        )
        record["http_status"] = response.status_code
        try:
            body = response.json()
            json.dumps(body, allow_nan=False)
            record["raw_response"] = body
        except ValueError:
            record["raw_response_text"] = response.text
        if response.status_code != 200:
            record["error_kind"] = "http_error"
        else:
            body = record["raw_response"]
            if not isinstance(body, dict) or "status" not in body:
                raise ValueError("Invalid retrieval response")
            if body["status"] != "success":
                record["error_kind"] = "upstream_error"
            else:
                chunks = body["data"]["chunks"]
                if not isinstance(chunks, list):
                    raise ValueError("Invalid chunks")
                for chunk in chunks:
                    if not isinstance(chunk, dict) or any(
                        not isinstance(chunk.get(key), str) or not chunk[key]
                        for key in ("chunk_id", "reference_id", "file_path", "content")
                    ):
                        raise ValueError("Invalid chunk fields")
                if len({c["chunk_id"] for c in chunks}) != len(chunks):
                    raise ValueError("Duplicate chunk IDs")
                metadata = body.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise ValueError("Invalid retrieval metadata")
                policy_metadata = metadata.get("doctrace_policy")
                if policy_metadata is not None and not isinstance(policy_metadata, dict):
                    raise ValueError("Invalid policy metadata")
                record["policy_metadata"] = (
                    dict(policy_metadata) if policy_metadata is not None else None
                )
                record["chunks"] = [dict(c) for c in chunks]
    except httpx.TimeoutException as error:
        record["error_kind"] = "timeout"
        record["transport_exception_type"] = type(error).__name__
    except httpx.RequestError as error:
        record["error_kind"] = "transport_error"
        record["transport_exception_type"] = type(error).__name__
    except (ValueError, KeyError, TypeError):
        record["error_kind"] = "invalid_response"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return record
