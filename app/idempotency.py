from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from .qa_records import (
    create_processing_record,
    get_qa_record_by_key,
)


class IdempotencyConflict(RuntimeError):
    def __init__(self, request_id: str):
        super().__init__("同一个幂等键不能用于不同的问题、知识库或检索模式.")
        self.request_id = request_id


def claim_qa_record(
    engine: Engine,
    *,
    question: str,
    corpus_id: str,
    idempotency_key: str,
    owner_user_id: str | None = None,
    request_mode: str = "mix",
) -> tuple[str, bool]:
    try:
        request_id = create_processing_record(
            engine,
            question=question,
            corpus_id=corpus_id,
            request_mode=request_mode,
            idempotency_key=idempotency_key,
            owner_user_id=owner_user_id,
        )
    except IntegrityError:
        original = get_qa_record_by_key(engine, idempotency_key, owner_user_id=owner_user_id)

        if original is None:
            raise

        if (
            original["question"] != question
            or original["corpus_id"] != corpus_id
            or original["request_mode"] != request_mode
        ):
            raise IdempotencyConflict(original["request_id"]) from None

        return original["request_id"], False

    return request_id, True
