from collections.abc import Callable
from time import perf_counter
from uuid import uuid4
from .idempotency import IdempotencyConflict, claim_qa_record
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
import json
from pydantic import ValidationError
from .lightrag_client import UpstreamError
from .qa_records import (
    RecordStateError,
    create_processing_record,
    save_completed_record,
    save_failed_record,
    get_qa_record,
)
from .schemas import AskResponse, MediumAskResponse
from .qa_logging import current_attempt_id, log_qa_event, qa_log_context


class RecordedQAError(UpstreamError):
    def __init__(
        self,
        error: UpstreamError,
        request_id: str | None,
    ):
        super().__init__(
            error.status_code,
            error.detail,
            stage=error.stage,
        )
        self.request_id = request_id


def persistence_error(request_id: str | None) -> RecordedQAError:
    return RecordedQAError(
        UpstreamError(
            503,
            "问答记录保存失败，请勿自动重复提交问题。",
            stage="记录保存",
        ),
        request_id,
    )

def load_existing_answer(
    engine: Engine,
    request_id: str,
    *, owner_user_id: str | None = None,
) -> MediumAskResponse:
    try:
        row = get_qa_record(engine, request_id, owner_user_id=owner_user_id)
    except SQLAlchemyError:
        raise RecordedQAError(
            UpstreamError(
                503,
                "暂时无法读取原请求记录。",
                stage="记录读取",
            ),
            request_id,
        ) from None

    invalid_record = UpstreamError(
        500,
        "已保存的问答记录格式异常。",
        stage="记录读取",
    )

    if row is None:
        error = UpstreamError(
            404, "原请求记录不存在。", stage="记录读取"
        )

    elif row["status"] == "processing":
        error = UpstreamError(
            409,
            "原请求尚未保存最终结果，请稍后查看历史记录。",
            stage="请求状态",
        )

    elif row["status"] == "failed":
        status_code = row["http_status"]
        if not isinstance(status_code, int) or not 400 <= status_code <= 599:
            status_code = 500

        error = UpstreamError(
            status_code,
            row["error_message"] or "原请求未成功完成。",
            stage=row["error_stage"] or "问答处理",
        )

    elif row["status"] == "completed":
        try:
            return MediumAskResponse(
                response=row["answer"],
                references=json.loads(row["references_json"]),
                retrieval=(
                    json.loads(row["retrieval_json"])
                    if row["retrieval_json"] is not None
                    else None
                ),
                llm_generated=row["llm_generated"],
            )
        except (ValueError, TypeError, KeyError, ValidationError):
            error = invalid_record

    else:
        error = invalid_record

    raise RecordedQAError(error, request_id)

def run_recorded_qa(
    engine: Engine,
    *,
    question: str,
    corpus_id: str,
    answer_fn: Callable[[], AskResponse],
    idempotency_key: str | None = None,
    owner_user_id: str | None = None,
    request_mode: str = "mix",
) -> tuple[str, AskResponse]:
    with qa_log_context(attempt_id=current_attempt_id() or str(uuid4())):
        return _run_recorded_qa(engine, question=question, corpus_id=corpus_id,
            answer_fn=answer_fn, idempotency_key=idempotency_key, owner_user_id=owner_user_id,request_mode=request_mode,)


def _run_recorded_qa(
    engine: Engine,
    *,
    question: str,
    corpus_id: str,
    answer_fn: Callable[[], AskResponse],
    idempotency_key: str | None,
    owner_user_id: str | None,
    request_mode: str = "mix",
) -> tuple[str, AskResponse]:
    started = perf_counter()
    log_qa_event("record_create_started", None, stage="记录保存")

    try:
        if idempotency_key is None:
            request_id = create_processing_record(
                engine,
                question=question,
                corpus_id=corpus_id,
                owner_user_id=owner_user_id,
                request_mode=request_mode,
            )
            created = True
        else:
            request_id, created = claim_qa_record(
                engine,
                question=question,
                corpus_id=corpus_id,
                idempotency_key=idempotency_key,
                owner_user_id=owner_user_id,
                request_mode=request_mode,
            )

    except IdempotencyConflict as error:
        log_qa_event("idempotency_conflict", error.request_id, stage="请求校验",
            http_status=409, duration_ms=int((perf_counter() - started) * 1000))
        raise RecordedQAError(
            UpstreamError(
                409,
                str(error),
                stage="请求校验",
            ),
            error.request_id,
        ) from None

    except (SQLAlchemyError, RecordStateError) as error:
        log_qa_event("record_create_failed", None, stage="记录保存", http_status=503,
            error_type=type(error).__name__, duration_ms=int((perf_counter() - started) * 1000))
        raise persistence_error(None) from None

    with qa_log_context(request_id=request_id):
        if not created:
            log_qa_event("record_reused", request_id,
                duration_ms=int((perf_counter() - started) * 1000))
            try:
                answer = load_existing_answer(engine, request_id, owner_user_id=owner_user_id)
            except RecordedQAError as error:
                log_qa_event("replay_failed", request_id, stage=error.stage,
                    http_status=error.status_code, duration_ms=int((perf_counter() - started) * 1000))
                raise
            log_qa_event("replay_completed", request_id, http_status=200,
                duration_ms=int((perf_counter() - started) * 1000))
            return request_id, answer

        log_qa_event("record_created", request_id,
            duration_ms=int((perf_counter() - started) * 1000))
        log_qa_event("qa_started", request_id)
        return _execute_new_qa(engine, request_id, answer_fn, started)


def _execute_new_qa(engine, request_id, answer_fn, started):

    try:
        answer = answer_fn()
    except Exception as original:
        if isinstance(original, UpstreamError):
            error = original
        else:
            error = UpstreamError(
                500,
                "问答处理发生内部错误。",
                stage="内部处理",
            )

        log_qa_event("qa_failed", request_id, stage=error.stage, http_status=error.status_code,
            error_type=type(original).__name__, duration_ms=int((perf_counter() - started) * 1000))
        save_started = perf_counter()
        try:
            log_qa_event("record_save_started", request_id, stage="记录保存", outcome="failed")
            save_failed_record(
                engine,
                request_id,
                error=error,
                duration_ms=int((perf_counter() - started) * 1000),
            )
        except (SQLAlchemyError, RecordStateError) as save_error:
            log_qa_event("record_save_failed", request_id, stage="记录保存", http_status=503,
                error_type=type(save_error).__name__, outcome="failed",
                duration_ms=int((perf_counter() - save_started) * 1000))
            raise persistence_error(request_id) from None

        log_qa_event("record_saved", request_id, stage="记录保存", outcome="failed",
            duration_ms=int((perf_counter() - save_started) * 1000))
        raise RecordedQAError(error, request_id) from None

    log_qa_event("answer_ready", request_id,
        outcome="generated" if answer.llm_generated else "non_generated")
    save_started = perf_counter()
    try:
        log_qa_event("record_save_started", request_id, stage="记录保存", outcome="completed")
        save_completed_record(
            engine,
            request_id,
            result=answer,
            duration_ms=int((perf_counter() - started) * 1000),
        )
    except (SQLAlchemyError, RecordStateError) as error:
        log_qa_event("record_save_failed", request_id, stage="记录保存", http_status=503,
            error_type=type(error).__name__, outcome="completed",
            duration_ms=int((perf_counter() - save_started) * 1000))
        raise persistence_error(request_id) from None

    log_qa_event("record_saved", request_id, stage="记录保存", outcome="completed",
        duration_ms=int((perf_counter() - save_started) * 1000))
    log_qa_event("qa_completed", request_id, http_status=200,
        duration_ms=int((perf_counter() - started) * 1000))
    return request_id, answer
