from datetime import datetime, timezone
from uuid import uuid4
import json

from .schemas import AskResponse
from sqlalchemy import Engine, text
from .lightrag_client import UpstreamError
def create_processing_record(
    engine: Engine,
    *,
    question: str,
    corpus_id: str,
    idempotency_key: str | None = None,
    owner_user_id: str | None = None,
    request_mode: str = "mix",
) -> str:
    if request_mode not in ("naive", "mix"):
        raise ValueError("request_mode must be naive or mix")
    request_id = str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        INSERT INTO qa_records (
            request_id,
            idempotency_key,
            owner_user_id,
            question,
            corpus_id,
            request_mode,
            status,
            created_at,
            updated_at
        )
        VALUES (
            :request_id,
            :idempotency_key,
            :owner_user_id,
            :question,
            :corpus_id,
            :request_mode,
            :status,
            :created_at,
            :updated_at
        )
    """)

    with engine.begin() as conn:
        conn.execute(
            statement,
            {
                "request_id": request_id,
                "idempotency_key": idempotency_key,    
                "owner_user_id": owner_user_id,
                "question": question,
                "corpus_id": corpus_id,
                "request_mode": request_mode,
                "status": "processing",
                "created_at": now,
                "updated_at": now,
            },
        )

    return request_id
class RecordStateError(RuntimeError):
    pass


def save_completed_record(
    engine: Engine,
    request_id: str,
    *,
    result: AskResponse,
    duration_ms: int,
) -> None:
    if duration_ms < 0:
        raise ValueError("duration_ms must not be negative")

    payload = result.model_dump(mode="json")
    retrieval = payload.get("retrieval")
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        UPDATE qa_records
        SET
            answer = :answer,
            references_json = :references_json,
            retrieval_json = :retrieval_json,
            status = 'completed',
            http_status = 200,
            llm_generated = :llm_generated,
            duration_ms = :duration_ms,
            updated_at = :updated_at
        WHERE request_id = :request_id
          AND status = 'processing'
    """)

    with engine.begin() as conn:
        update_result = conn.execute(
            statement,
            {
                "request_id": request_id,
                "answer": result.response,
                "references_json": json.dumps(
                    payload["references"], ensure_ascii=False
                ),
                "retrieval_json": (
                    json.dumps(retrieval, ensure_ascii=False)
                    if retrieval is not None
                    else None
                ),
                "llm_generated": result.llm_generated,
                "duration_ms": duration_ms,
                "updated_at": now,
            },
        )

        if update_result.rowcount != 1:
            raise RecordStateError(
                "Record does not exist or is no longer processing."
            )
def save_failed_record(
    engine: Engine,
    request_id: str,
    *,
    error: UpstreamError,
    duration_ms: int,
) -> None:
    if duration_ms < 0:
        raise ValueError("duration_ms must not be negative")

    if not 400 <= error.status_code <= 599:
        raise ValueError("Failure HTTP status must be between 400 and 599")

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        UPDATE qa_records
        SET
            status = 'failed',
            http_status = :http_status,
            error_stage = :error_stage,
            error_message = :error_message,
            duration_ms = :duration_ms,
            updated_at = :updated_at
        WHERE request_id = :request_id
          AND status = 'processing'
    """)

    with engine.begin() as conn:
        update_result = conn.execute(
            statement,
            {
                "request_id": request_id,
                "http_status": error.status_code,
                "error_stage": error.stage or "unknown",
                "error_message": error.detail,
                "duration_ms": duration_ms,
                "updated_at": now,
            },
        )

        if update_result.rowcount != 1:
            raise RecordStateError(
                "Record does not exist or is no longer processing."
            )

def get_qa_record(
    engine: Engine,
    request_id: str,
    *, owner_user_id: str | None = None,
) -> dict | None:
    statement = text("""
        SELECT
            request_id,
            question,
            answer,
            references_json,
            retrieval_json,
            corpus_id,
            request_mode,
            status,
            http_status,
            error_stage,
            error_message,
            llm_generated,
            duration_ms,
            created_at,
            updated_at
        FROM qa_records
        WHERE request_id = :request_id
          AND (:owner_user_id IS NULL OR owner_user_id = :owner_user_id)
    """)

    with engine.connect() as conn:
        row = conn.execute(
            statement,
            {"request_id": request_id, "owner_user_id": owner_user_id},
        ).mappings().first()

    return dict(row) if row is not None else None

def get_qa_record_by_key(
    engine: Engine,
    idempotency_key: str,
    *, owner_user_id: str | None = None,
) -> dict | None:
    statement = text("""
        SELECT
            request_id,
            question,
            answer,
            references_json,
            retrieval_json,
            corpus_id,
            request_mode,
            status,
            http_status,
            error_stage,
            error_message,
            llm_generated,
            duration_ms,
            created_at,
            updated_at
        FROM qa_records
        WHERE idempotency_key = :idempotency_key
          AND ((:owner_user_id IS NULL AND owner_user_id IS NULL)
               OR owner_user_id = :owner_user_id)
    """)

    with engine.connect() as conn:
        row = conn.execute(
            statement,
            {"idempotency_key": idempotency_key, "owner_user_id": owner_user_id},
        ).mappings().first()

    return dict(row) if row is not None else None

def list_qa_records(
    engine: Engine,
    *,
    limit: int = 20,
    offset: int = 0,
    owner_user_id: str | None = None,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")

    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")

    statement = text("""
        SELECT
            request_id,
            question,
            corpus_id,
            status,
            http_status,
            duration_ms,
            created_at,
            updated_at
        FROM qa_records
        WHERE (:owner_user_id IS NULL OR owner_user_id = :owner_user_id)
        ORDER BY created_at DESC, request_id DESC
        LIMIT :fetch_limit OFFSET :offset
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            statement,
            {
                "fetch_limit": limit + 1,
                "offset": offset,
                "owner_user_id": owner_user_id,
            },
        ).mappings().all()

    has_more = len(rows) > limit

    return {
        "items": [dict(row) for row in rows[:limit]],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }
