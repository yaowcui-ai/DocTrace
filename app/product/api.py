"""Same-origin, owner-scoped product routes with explicit admin authorization."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import auth_http
from ..auth_routes import read_current_user
from ..config import ConfigurationError
from . import repository as repo, service
from .schemas import (Envelope, IdentityOutput, ConversationOutput, ConversationPage,
    ConversationDetail, MessageOutput, ImportOutput, FeedbackOutput)
from ..schemas import Reference


class ProductRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def guarded(request):
            try:
                if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                    auth_http.require_trusted_json(request)
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(status_code=422, content={'detail': '请求格式不正确。'})
            except ConfigurationError:
                response = JSONResponse(status_code=503, content={'detail': '身份服务配置不可用。'})
            except SQLAlchemyError:
                response = JSONResponse(status_code=503, content={'detail': '数据服务暂时不可用，请稍后重试。'})
            except (ValidationError, ValueError, TypeError, KeyError):
                response = JSONResponse(status_code=500, content={'detail': '已保存的数据格式异常。'})
            except StarletteHTTPException as error:
                response = JSONResponse(status_code=error.status_code, content={'detail': error.detail}, headers=error.headers)
            response.headers['Cache-Control'] = 'no-store'
            return response
        return guarded


router = APIRouter(prefix='/api/v1', tags=['product'], route_class=ProductRoute)


def get_engine(request: Request):
    engine = getattr(request.app.state, 'db_engine', None)
    if engine is None:
        raise HTTPException(503, '数据服务暂时不可用。')
    return engine


def current_role(request: Request, user=Depends(read_current_user)):
    return repo.get_role(get_engine(request), str(user.user_id))


def require_admin(request: Request, user=Depends(read_current_user)):
    if repo.get_role(get_engine(request), str(user.user_id)) != 'admin':
        raise HTTPException(403, '需要管理员权限。')
    return user


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(default='新会话', strict=True, min_length=1, max_length=120)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    question: str = Field(strict=True, min_length=1, max_length=2000)
    mode: Literal['naive', 'mix'] = 'naive'
    knowledge_base: Literal['frozen', 'managed'] = 'frozen'


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    helpful: bool = Field(strict=True)
    comment: str = Field(default='', strict=True, max_length=2000)


@router.get('/me', response_model=Envelope[IdentityOutput])
def me(request: Request, user=Depends(read_current_user)):
    return {'data': {**user.model_dump(mode='json'), 'role': repo.get_role(get_engine(request), str(user.user_id))}}


@router.get('/conversations', response_model=Envelope[ConversationPage])
def conversations(request: Request, user=Depends(read_current_user), q: str = Query(default='', max_length=200),
        limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)):
    return {'data': repo.list_conversations(get_engine(request), str(user.user_id), q.strip(), limit, offset)}


@router.post('/conversations', response_model=Envelope[ConversationOutput])
def create_conversation(payload: ConversationInput, request: Request, user=Depends(read_current_user)):
    return {'data': repo.create_conversation(get_engine(request), str(user.user_id), payload.title)}


@router.post('/conversations/import-records', response_model=Envelope[ImportOutput])
def import_records(request: Request, user=Depends(read_current_user), limit: int = Query(default=100, ge=1, le=100)):
    return {'data': repo.import_legacy_records(get_engine(request), str(user.user_id), limit)}


@router.get('/conversations/{conversation_id}', response_model=Envelope[ConversationDetail])
def conversation(conversation_id: UUID, request: Request, user=Depends(read_current_user),
        limit: int = Query(default=100, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)):
    engine, owner = get_engine(request), str(user.user_id)
    result = service.require_conversation(engine, owner, str(conversation_id))
    result['messages'], result['has_more'] = repo.list_messages(engine, owner, str(conversation_id), limit, offset)
    result['offset'] = offset
    result['next_offset'] = offset + limit if result['has_more'] else None
    return {'data': result}


@router.post('/conversations/{conversation_id}/messages', response_model=Envelope[MessageOutput])
def send_message(conversation_id: UUID, payload: MessageInput, request: Request,
        idempotency_key: UUID = Header(alias='Idempotency-Key'), user=Depends(read_current_user)):
    return {'data': service.submit_message(get_engine(request), str(user.user_id), str(conversation_id),
        payload.question, payload.mode, str(idempotency_key), request, user, knowledge_base=payload.knowledge_base)}


@router.put('/messages/{request_id}/feedback', response_model=Envelope[FeedbackOutput])
def update_feedback(request_id: UUID, payload: FeedbackInput, request: Request, user=Depends(read_current_user)):
    engine, owner = get_engine(request), str(user.user_id)
    message = repo.get_message(engine, owner, request_id=str(request_id))
    if message is None:
        raise HTTPException(404, '问答消息不存在。')
    if message['status'] != 'completed':
        raise HTTPException(409, '只能评价已完成的问答。')
    return {'data': repo.save_feedback(engine, owner, str(request_id), payload.helpful, payload.comment)}


@router.get('/citations/{request_id}/{reference_id}', response_model=Envelope[Reference])
def citation(request_id: UUID, reference_id: str, request: Request, user=Depends(read_current_user)):
    # Read only the owned, recorded snapshot; client-controlled filenames never reach disk.
    from ..qa_records import get_qa_record
    record = get_qa_record(get_engine(request), str(request_id), owner_user_id=str(user.user_id))
    if record is None or len(reference_id) > 128:
        raise HTTPException(404, '引用不存在。')
    for reference in repo.sanitized_references(record['references_json']):
        if reference['reference_id'] == reference_id:
            return {'data': reference}
    raise HTTPException(404, '引用不存在。')
