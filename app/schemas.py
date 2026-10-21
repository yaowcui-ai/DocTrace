from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(strict=True, min_length=1, max_length=2000)

class OptimizedAskRequest(AskRequest):
    mode: Literal["naive", "mix"] = "naive"
class Reference(BaseModel):
    reference_id: str
    file_path: str
    content: list[str] | None = None


class RetrievalInfo(BaseModel):
    mode: str
    policy_version: str
    strategy: str
    degraded: bool


class AskResponse(BaseModel):
    response: str
    references: list[Reference]
    response_time: float | None = None
    llm_generated: bool


class MediumAskResponse(AskResponse):
    retrieval: RetrievalInfo | None = None


class RecordedAskResponse(MediumAskResponse):
    request_id: str = Field(
        strict=True,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )


class QARecordResponse(BaseModel):
    request_id: UUID
    question: str
    answer: str | None
    references: list[Reference] | None
    retrieval: RetrievalInfo | None
    corpus_id: str
    status: Literal["processing", "completed", "failed"]
    http_status: int | None
    error_stage: str | None
    error_message: str | None
    llm_generated: bool | None
    duration_ms: int | None = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        # MySQL DATETIME has no timezone; our write functions always store UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class QARecordSummary(BaseModel):
    request_id: UUID
    question: str
    corpus_id: str
    status: Literal["processing", "completed", "failed"]
    http_status: int | None
    duration_ms: int | None = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class QARecordListResponse(BaseModel):
    items: list[QARecordSummary]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(ge=0)
