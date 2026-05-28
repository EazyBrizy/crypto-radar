from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MarketPairOption(BaseModel):
    id: UUID
    exchange: str
    symbol: str
    base_asset: str
    quote_asset: str
    status: str


class WatchlistPairResponse(MarketPairOption):
    added_at: datetime


class WatchlistResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    is_default: bool
    pairs: list[WatchlistPairResponse]
    created_at: datetime


class WatchlistCreateRequest(BaseModel):
    user_id: str = "demo_user"
    name: str = Field(..., min_length=1)
    is_default: bool = False


class WatchlistUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    is_default: bool | None = None


class WatchlistPairCreateRequest(BaseModel):
    user_id: str = "demo_user"
    pair_id: UUID | None = None
    exchange: str | None = None
    symbol: str | None = None


class AlertRuleResponse(BaseModel):
    id: UUID
    user_id: UUID
    pair: MarketPairOption | None
    strategy_version_id: UUID | None
    condition_type: str
    condition_body: dict[str, Any]
    channels: list[str]
    is_enabled: bool
    created_at: datetime


class AlertRuleCreateRequest(BaseModel):
    user_id: str = "demo_user"
    pair_id: UUID | None = None
    strategy_version_id: UUID | None = None
    condition_type: str = Field(..., min_length=1)
    condition_body: dict[str, Any]
    channels: list[str] = Field(default_factory=lambda: ["websocket"])
    is_enabled: bool = True


class AlertRuleUpdateRequest(BaseModel):
    pair_id: UUID | None = None
    strategy_version_id: UUID | None = None
    condition_type: str | None = Field(default=None, min_length=1)
    condition_body: dict[str, Any] | None = None
    channels: list[str] | None = None
    is_enabled: bool | None = None


class AlertRuleTestResponse(BaseModel):
    status: Literal["stubbed"] = "stubbed"
    alert_rule: AlertRuleResponse
    event: dict[str, Any]
