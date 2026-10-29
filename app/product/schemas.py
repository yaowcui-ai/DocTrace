"""Versioned response contracts shared by OpenAPI and runtime response validation."""
from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from ..schemas import Reference, RetrievalInfo

T = TypeVar('T')


class Envelope(BaseModel, Generic[T]):
    data: T


class IdentityOutput(BaseModel):
    user_id: UUID
    username: str
    role: Literal['user', 'admin']


class ConversationOutput(BaseModel):
    id: UUID
    owner_user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class FeedbackValue(BaseModel):
    helpful: bool
    comment: str


class MessageOutput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    id: UUID
    conversation_id: UUID
    request_id: UUID | None
    question: str
    mode: Literal['naive', 'mix']
    knowledge_base: Literal['frozen', 'managed'] = 'frozen'
    corpus_id: str | None = None
    actual_mode: Literal['naive', 'mix'] | None = None
    historical_import: bool = False
    status: Literal['processing', 'completed', 'failed']
    answer: str | None
    references: list[Reference]
    retrieval: RetrievalInfo | None
    created_at: datetime
    query_text: str
    context_method: str
    http_status: int | None
    error_stage: str | None
    duration_ms: int | None = Field(ge=0)
    llm_generated: bool | None
    feedback: FeedbackValue | None


class ConversationDetail(ConversationOutput):
    messages: list[MessageOutput]
    has_more: bool
    offset: int = 0
    next_offset: int | None = None


class ConversationPage(BaseModel):
    items: list[ConversationOutput]
    limit: int
    offset: int = 0
    has_more: bool
    next_offset: int | None = None


class ImportOutput(BaseModel):
    imported: int
    skipped: int
    has_more: bool


class FeedbackOutput(FeedbackValue):
    request_id: UUID
    updated_at: datetime
