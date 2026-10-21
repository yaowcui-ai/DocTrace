"""Explicit public fields: no user IDs, private record IDs, or processing metadata."""
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import Reference
from .citation_audit import audit_citations


class PublicDraftReference(Reference):
    model_config = ConfigDict(strict=True, extra='forbid')
    reference_id: str = Field(pattern=r'^[1-9][0-9]*$')
    content: list[str] = Field(min_length=1)

    @field_validator('file_path')
    @classmethod
    def only_a_display_filename(cls, value: str) -> str:
        if not value.strip() or value in {'.', '..'} or any(c in value for c in ('/', '\\', ':')):
            raise ValueError('Use a public display filename, not an internal path.')
        return value

    @field_validator('content')
    @classmethod
    def evidence_is_not_blank(cls, value: list[str]) -> list[str]:
        if any(not part.strip() for part in value):
            raise ValueError('Evidence must not be blank.')
        return value


class PublicExampleDraft(BaseModel):
    """Structural checks cannot replace the human privacy/factual review."""
    model_config = ConfigDict(strict=True, extra='forbid')
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1)
    references: list[PublicDraftReference] = Field(min_length=1)
    corpus_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')

    @field_validator('question', 'answer')
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Text must not be blank.')
        return value

    @model_validator(mode='after')
    def reference_ids_match_answer(self):
        identifiers = [ref.reference_id for ref in self.references]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('Reference identifiers must be unique.')
        audit = audit_citations(self.answer, [ref.model_dump() for ref in self.references])
        if not audit['has_citations'] or not audit['ids_valid'] or not audit['format_valid']:
            raise ValueError('Answer citations must point to included evidence.')
        return self


class PublicExampleSummary(BaseModel):
    example_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    corpus_id: str
    published_at: datetime

    @field_validator('published_at')
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class PublicExampleResponse(PublicExampleSummary):
    answer: str = Field(min_length=1)
    references: list[Reference]


class PublicExampleListResponse(BaseModel):
    items: list[PublicExampleSummary]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    has_more: bool
    next_offset: int | None = Field(ge=0)
