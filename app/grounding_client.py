"""Collect a single offline review, preserving invalid output and request failures."""

import json
import time

import httpx2 as httpx

from .answer_config import AnswerSettings
from .grounding_prompt import build_grounding_messages
from .grounding_review import validate_grounding_review


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def collect_grounding_review(
    client, settings: AnswerSettings, question: str, answer_text: str, references: list[dict],
    *, review_window: dict | None = None,
) -> dict:
    record = {"http_status": None, "error_kind": None, "raw_response": None,
              "parsed_review": None, "result": None}
    started = time.perf_counter()
    messages = build_grounding_messages(question, answer_text, references, review_window=review_window)
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
                raise ValueError("Invalid review response")
            choice = body["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError("Invalid review choice")
            message = choice["message"]
            content = message.get("content")
            if message.get("role") != "assistant" or not isinstance(content, str) or not content.strip():
                raise ValueError("Invalid review content")
            if choice["finish_reason"] != "stop":
                record["error_kind"] = "incomplete_response"
            else:
                try:
                    parsed = json.loads(content, object_pairs_hook=_unique_object)
                    json.dumps(parsed, allow_nan=False)
                    record["parsed_review"] = parsed
                    record["result"] = validate_grounding_review(parsed, answer_text, references)
                except (ValueError, TypeError):
                    record["error_kind"] = "invalid_review"
    except httpx.TimeoutException as error:
        record["error_kind"] = "timeout"
        record["transport_exception_type"] = type(error).__name__
    except httpx.RequestError as error:
        record["error_kind"] = "transport_error"
        record["transport_exception_type"] = type(error).__name__
    except (ValueError, KeyError, TypeError, IndexError):
        record["error_kind"] = "invalid_response"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return record
