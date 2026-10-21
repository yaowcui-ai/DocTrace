"""Collect a complete reranking response without retrying or selecting evidence."""

import json
import time

import httpx2 as httpx

from .rerank import map_rerank_results
from .rerank_config import RerankSettings


def collect_rerank(client, settings: RerankSettings, question: str, chunks: list[dict]) -> dict:
    record = {"http_status": None, "error_kind": None,
              "raw_response": None, "ranked_chunks": None}
    started = time.perf_counter()
    try:
        response = client.post(
            settings.rerank_url,
            headers={"Authorization": f"Bearer {settings.rerank_api_key}"},
            json={"model": settings.rerank_model, "query": question,
                  "documents": [chunk["content"] for chunk in chunks],
                  "top_n": len(chunks), "return_documents": False},
        )
        record["http_status"] = response.status_code
        # Retain parsed provider errors too, without recording request headers.
        try:
            parsed = response.json()
            json.dumps(parsed, allow_nan=False)
            record["raw_response"] = parsed
        except ValueError:
            record["raw_response_text"] = response.text
        if response.status_code != 200:
            record["error_kind"] = "http_error"
        else:
            body = record["raw_response"]
            if not isinstance(body, dict) or not isinstance(body.get("results"), list):
                raise ValueError("Invalid provider response")
            record["ranked_chunks"] = map_rerank_results(chunks, body["results"])
    except httpx.TimeoutException:
        record["error_kind"] = "timeout"
    except httpx.RequestError:
        record["error_kind"] = "transport_error"
    except (ValueError, KeyError, TypeError):
        record["error_kind"] = "invalid_response"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return record
