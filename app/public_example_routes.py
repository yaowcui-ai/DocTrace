"""Anonymous read-only published snapshots, independent of private QA records."""
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .public_examples import get_published_example, list_published_examples
from .public_example_schemas import PublicExampleListResponse, PublicExampleResponse

router = APIRouter(prefix='/examples', tags=['public examples'])


def example_engine(request: Request):
    engine = getattr(request.app.state, 'db_engine', None)
    if engine is None:
        raise HTTPException(503, '公开示例服务暂时不可用。')
    return engine


@router.get('', response_model=PublicExampleListResponse)
def read_public_examples(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    engine = example_engine(request)
    try:
        page = list_published_examples(engine, limit=limit, offset=offset)
    except SQLAlchemyError:
        raise HTTPException(503, '暂时无法读取公开示例。') from None
    try:
        return PublicExampleListResponse.model_validate(page)
    except ValidationError:
        raise HTTPException(500, '已发布示例的数据格式异常。') from None


@router.get('/{example_id}', response_model=PublicExampleResponse)
def read_public_example(example_id: UUID, request: Request):
    engine = example_engine(request)
    try:
        row = get_published_example(engine, str(example_id))
    except SQLAlchemyError:
        raise HTTPException(503, '暂时无法读取公开示例。') from None
    if row is None:
        raise HTTPException(404, '公开示例不存在。')
    try:
        row['references'] = json.loads(row.pop('references_json'))
        return PublicExampleResponse.model_validate(row)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(500, '已发布示例的数据格式异常。') from None
