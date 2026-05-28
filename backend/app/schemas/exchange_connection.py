from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ExchangeConnectionResponse(BaseModel):
    id: UUID
    user_id: UUID
    exchange_id: UUID
    exchange_code: str
    exchange_name: str
    label: str
    account_type: str
    key_ref: str
    permissions: dict[str, Any]
    status: str
    last_sync_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime


class ExchangeConnectionCreateRequest(BaseModel):
    user_id: str = "demo_user"
    exchange_code: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    account_type: str = "spot"
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None
    permissions: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExchangeConnectionUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1)
    account_type: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    api_passphrase: str | None = None
    permissions: dict[str, Any] | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None


class ExchangeConnectionActionResponse(BaseModel):
    connection: ExchangeConnectionResponse
    status: str = "stubbed"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
