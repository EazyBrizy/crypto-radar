from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.candle import Timeframe


class StrategyPairScope(BaseModel):
    exchange: str
    symbol: str


class StrategyConfigResponse(BaseModel):
    id: UUID
    user_id: UUID
    strategy_version_id: UUID
    strategy_code: str
    strategy_name: str
    strategy_version: str
    name: str
    exchanges: list[str]
    pairs: list[StrategyPairScope]
    timeframes: list[Timeframe]
    params: dict[str, Any]
    risk_settings: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class StrategyConfigUpdateRequest(BaseModel):
    user_id: str = "demo_user"
    name: str | None = Field(default=None, min_length=1)
    exchanges: list[str] | None = None
    pairs: list[StrategyPairScope] | None = None
    timeframes: list[Timeframe] | None = None
    params: dict[str, Any] | None = None
    risk_settings: dict[str, Any] | None = None
    is_enabled: bool | None = None
