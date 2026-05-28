from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


NORMALIZED_REAL_TRADE_TARGETS = [
    "external_exchange_orders",
    "external_exchange_trades",
]
ANALYTICS_REAL_TRADE_TARGETS = [
    "analytics.external_trade_events",
]
RAW_REAL_TRADE_TARGETS = [
    "market.raw_exchange_events",
]


class ExternalExchangeOrderResponse(BaseModel):
    id: UUID
    user_id: UUID
    connection_id: UUID
    exchange_order_id: str
    pair_id: UUID
    exchange_code: str
    symbol: str
    side: str
    order_type: str | None
    status: str | None
    quantity: Decimal | None
    price: Decimal | None
    created_exchange_at: datetime | None
    updated_exchange_at: datetime | None
    imported_at: datetime
    metadata: dict[str, Any]


class ExternalExchangeTradeResponse(BaseModel):
    id: UUID
    user_id: UUID
    connection_id: UUID
    exchange_trade_id: str
    exchange_order_id: str | None
    pair_id: UUID
    exchange_code: str
    symbol: str
    side: str
    price: Decimal
    quantity: Decimal
    fee_amount: Decimal | None
    fee_asset_id: UUID | None
    fee_asset_symbol: str | None
    traded_at: datetime
    imported_at: datetime
    metadata: dict[str, Any]


class RealTradeImportRequest(BaseModel):
    connection_id: UUID
    since: datetime | None = None
    until: datetime | None = None
    symbols: list[str] = Field(default_factory=list)
    dry_run: bool = False


class RealTradeImportNotReadyResponse(BaseModel):
    status: Literal["not_implemented"] = "not_implemented"
    message: str
    connection_id: UUID | None = None
    connector_required: bool = True
    normalized_targets: list[str] = Field(default_factory=lambda: NORMALIZED_REAL_TRADE_TARGETS.copy())
    analytics_targets: list[str] = Field(default_factory=lambda: ANALYTICS_REAL_TRADE_TARGETS.copy())
    raw_targets: list[str] = Field(default_factory=lambda: RAW_REAL_TRADE_TARGETS.copy())
    details: dict[str, Any] = Field(default_factory=dict)


class RealTradeImportResult(BaseModel):
    status: Literal["completed", "dry_run"]
    connection_id: UUID
    external_exchange_orders_written: int = 0
    external_exchange_trades_written: int = 0
    analytics_events_written: int = 0
    raw_events_written: int = 0
    started_at: datetime
    finished_at: datetime
