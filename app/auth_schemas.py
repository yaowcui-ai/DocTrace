"""Authentication request and public identity shapes; preserve password whitespace."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .users import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    username: str = Field(pattern=r"^[a-z][a-z0-9_]{2,31}$")
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    username: str
