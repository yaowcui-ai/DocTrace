"""Administrator-only document content, versions and durable task controls."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.product.api import ProductRoute, require_admin, get_engine
from .repository import KnowledgeRepository

router = APIRouter(prefix='/api/v1/admin', tags=['managed knowledge'], route_class=ProductRoute,
    dependencies=[Depends(require_admin)])


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(strict=True, min_length=1, max_length=180)
    content: str = Field(strict=True, min_length=1, max_length=1048576)


def invoke(request, method, *args):
    try:
        result = getattr(KnowledgeRepository(get_engine(request)), method)(*args)
        return {'data': result}
    except KeyError:
        raise HTTPException(404, '文档或任务不存在。') from None
    except ValueError as error:
        # Repository validation messages are fixed strings and never interpolate input.
        status = 422 if method == 'create' else 409
        raise HTTPException(status, str(error)) from None


@router.get('/documents')
def list_documents(request: Request):
    return invoke(request, 'list')


@router.post('/documents')
def create_document(payload: DocumentInput, request: Request):
    return invoke(request, 'create', payload.filename, payload.content)


@router.get('/documents/{doc_id}')
def document(doc_id: UUID, request: Request):
    return invoke(request, 'get', str(doc_id))


@router.put('/documents/{doc_id}')
def update_document(doc_id: UUID, payload: DocumentInput, request: Request):
    return invoke(request, 'update', str(doc_id), payload.filename, payload.content)


@router.delete('/documents/{doc_id}')
def retire_document(doc_id: UUID, request: Request):
    return invoke(request, 'retire', str(doc_id))


@router.post('/documents/{doc_id}/index')
def index_document(doc_id: UUID, request: Request):
    return invoke(request, 'enqueue', str(doc_id))


@router.get('/tasks')
def tasks(request: Request):
    return invoke(request, 'tasks')


@router.get('/tasks/{task_id}')
def task(task_id: UUID, request: Request):
    return invoke(request, 'task', str(task_id))
