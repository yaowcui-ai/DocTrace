"""Call the answering model with supplied evidence, preserving failures and raw output."""

import json
import time

import httpx2 as httpx

from .answer_config import AnswerSettings
from .answer_prompt import build_answer_messages
from .schemas import AskResponse


def collect_answer(client, settings: AnswerSettings, question: str, evidence_bundle: dict) -> dict:
    record = {"http_status": None, "error_kind": None, "raw_response": None, "result": None}
    started = time.perf_counter()
    try:
        messages = build_answer_messages(question, evidence_bundle)
    except (ValueError, KeyError, TypeError):
        record["error_kind"] = "invalid_input"
        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return record

    try:
        response = client.post(
            settings.answer_url,
            headers={"Authorization": f"Bearer {settings.answer_api_key}"},
            json={"model": settings.answer_model, "messages": messages,
                  "stream": False, "thinking": {"type": "disabled"}},
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
            if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
                raise ValueError("Invalid answer response")
            choice = body["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError("Invalid answer choice")
            message = choice["message"]
            content = message.get("content")
            if message.get("role") != "assistant" or not isinstance(content, str) or not content.strip():
                raise ValueError("Invalid answer content")
            if choice["finish_reason"] != "stop":
                record["error_kind"] = "incomplete_response"
            else:
                record["result"] = AskResponse.model_validate({
                    "response": content, "references": evidence_bundle["references"],
                    "llm_generated": True,
                }, strict=True).model_dump()
    except httpx.TimeoutException as error:
        record["error_kind"] = "timeout"
        record["transport_exception_type"] = type(error).__name__
    except httpx.RequestError as error:
        record["error_kind"] = "transport_error"
        record["transport_exception_type"] = type(error).__name__
    except (ValueError, KeyError, TypeError, IndexError):
        record["error_kind"] = "invalid_response"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    if record["result"] is not None:
        record["result"]["response_time"] = record["elapsed_seconds"]
    return record
