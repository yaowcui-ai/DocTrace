import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter


logger = logging.getLogger("doctrace.qa")
_record_id = ContextVar("qa_record_id", default=None)
_attempt_id = ContextVar("qa_attempt_id", default=None)


def current_attempt_id() -> str | None:
    return _attempt_id.get()


@contextmanager
def qa_log_context(*, request_id: str | None = None, attempt_id: str | None = None):
    """ContextVars isolate synchronous, threaded and async request executions."""
    tokens = []
    try:
        for variable, value in ((_record_id, request_id), (_attempt_id, attempt_id)):
            if value is not None:
                tokens.append((variable, variable.set(value)))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def log_qa_event(
    event: str,
    request_id: str | None,
    *,
    stage: str | None = None,
    duration_ms: int | None = None,
    http_status: int | None = None,
    error_type: str | None = None,
    chunk_count: int | None = None,
    strategy: str | None = None,
    degraded: bool | None = None,
    outcome: str | None = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "request_id": request_id if request_id is not None else _record_id.get(),
    }
    if _attempt_id.get() is not None:
        payload["attempt_id"] = _attempt_id.get()

    for name, value in (
        ("stage", stage),
        ("duration_ms", duration_ms),
        ("http_status", http_status),
        ("error_type", error_type),
        ("chunk_count", chunk_count),
        ("strategy", strategy),
        ("degraded", degraded),
        ("outcome", outcome),
    ):
        if value is not None:
            payload[name] = value

    try:
        logger.info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        # A logging sink failure must not retry generation or alter DB state.
        pass


@contextmanager
def qa_stage(stage: str):
    started = perf_counter()
    log_qa_event("stage_started", None, stage=stage)
    try:
        yield
    except Exception as error:
        log_qa_event("stage_failed", None, stage=stage,
            duration_ms=int((perf_counter() - started) * 1000),
            http_status=getattr(error, "status_code", 500),
            error_type=type(error).__name__)
        raise
    else:
        log_qa_event("stage_completed", None, stage=stage,
            duration_ms=int((perf_counter() - started) * 1000))
