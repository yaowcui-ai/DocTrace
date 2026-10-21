from sqlalchemy import Engine, text
from datetime import datetime, timezone
from uuid import uuid4
import json

from .public_example_schemas import PublicExampleDraft


def get_published_example(
    engine: Engine,
    example_id: str,
) -> dict | None:
    statement = text("""
        SELECT
            example_id,
            question,
            answer,
            references_json,
            corpus_id,
            published_at
        FROM public_examples
        WHERE example_id = :example_id
          AND status = 'published'
    """)

    with engine.connect() as conn:
        row = conn.execute(
            statement,
            {"example_id": example_id},
        ).mappings().first()

    return dict(row) if row is not None else None


def list_published_examples(
    engine: Engine,
    *,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('limit must be an integer from 1 to 100')
    if type(offset) is not int or offset < 0:
        raise ValueError('offset must be a non-negative integer')
    statement = text('''
        SELECT example_id, question, corpus_id, published_at
        FROM public_examples
        WHERE status = 'published'
        ORDER BY published_at DESC, example_id DESC
        LIMIT :fetch_limit OFFSET :offset
    ''')
    with engine.connect() as conn:
        rows = conn.execute(statement, {
            'fetch_limit': limit + 1,
            'offset': offset,
        }).mappings().all()
    has_more = len(rows) > limit
    return {
        'items': [dict(row) for row in rows[:limit]],
        'limit': limit,
        'offset': offset,
        'has_more': has_more,
        'next_offset': offset + limit if has_more else None,
    }
def create_public_example_draft(
    engine: Engine,
    *,
    payload: dict,
) -> str:
    data = PublicExampleDraft.model_validate(payload).model_dump(
        mode="json"
    )

    example_id = str(uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        INSERT INTO public_examples (
            example_id,
            question,
            answer,
            references_json,
            corpus_id,
            status,
            created_at,
            updated_at,
            published_at
        )
        VALUES (
            :example_id,
            :question,
            :answer,
            :references_json,
            :corpus_id,
            'draft',
            :created_at,
            :updated_at,
            NULL
        )
    """)

    with engine.begin() as conn:
        conn.execute(
            statement,
            {
                "example_id": example_id,
                "question": data["question"],
                "answer": data["answer"],
                "references_json": json.dumps(
                    data["references"],
                    ensure_ascii=False,
                ),
                "corpus_id": data["corpus_id"],
                "created_at": now,
                "updated_at": now,
            },
        )

    return example_id

def publish_public_example(
    engine: Engine,
    example_id: str,
) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    statement = text("""
        UPDATE public_examples
        SET
            status = 'published',
            published_at = :now,
            updated_at = :now
        WHERE example_id = :example_id
          AND status = 'draft'
    """)

    with engine.begin() as conn:
        result = conn.execute(
            statement,
            {
                "example_id": example_id,
                "now": now,
            },
        )

    return result.rowcount == 1