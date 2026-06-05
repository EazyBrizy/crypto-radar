from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ExchangeConnectionStatus = Literal["active", "disabled", "revoked", "deleted"]


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
    status: ExchangeConnectionStatus
    last_sync_at: datetime | None
    revoked_at: datetime | None = None
    deleted_at: datetime | None = None
    deletion_reason: str | None = None
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
    status: ExchangeConnectionStatus | None = None
    metadata: dict[str, Any] | None = None


class ExchangeConnectionActionResponse(BaseModel):
    connection: ExchangeConnectionResponse
    status: str = "stubbed"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ExchangeFeeRateResponse(BaseModel):
    connection_id: UUID
    exchange_code: str
    account_type: str | None = None
    category: str
    symbol: str | None
    maker_fee_rate: float = Field(..., ge=0)
    taker_fee_rate: float = Field(..., ge=0)
    source: str
    fetched_at: datetime


class ExchangeWalletCoinBalance(BaseModel):
    coin: str
    equity: Decimal | None = Field(default=None, ge=0)
    usd_value: Decimal | None = Field(default=None, ge=0)
    wallet_balance: Decimal | None = Field(default=None, ge=0)
    available_to_withdraw: Decimal | None = Field(default=None, ge=0)
    locked: Decimal | None = Field(default=None, ge=0)
    borrow_amount: Decimal | None = Field(default=None, ge=0)
    accrued_interest: Decimal | None = Field(default=None, ge=0)
    total_order_im: Decimal | None = Field(default=None, ge=0)
    total_position_im: Decimal | None = Field(default=None, ge=0)
    total_position_mm: Decimal | None = Field(default=None, ge=0)
    unrealised_pnl: Decimal | None = None


class ExchangeWalletBalanceResponse(BaseModel):
    exchange: str
    connection_id: UUID
    account_type: str
    total_equity: Decimal | None = Field(default=None, ge=0)
    total_wallet_balance: Decimal | None = Field(default=None, ge=0)
    total_available_balance: Decimal | None = Field(default=None, ge=0)
    coins: list[ExchangeWalletCoinBalance] = Field(default_factory=list)
    fetched_at: datetime | None = None
    status: Literal["fresh", "stale", "missing"]
    warnings: list[str] = Field(default_factory=list)


class ExchangeInstrumentRuleResponse(BaseModel):
    id: UUID
    exchange_id: UUID
    exchange_code: str
    pair_id: UUID | None
    symbol: str
    category: str
    min_order_size: float | None = Field(default=None, ge=0)
    max_order_size: float | None = Field(default=None, ge=0)
    min_notional: float | None = Field(default=None, ge=0)
    qty_step: float | None = Field(default=None, gt=0)
    tick_size: float | None = Field(default=None, gt=0)
    max_leverage: int | None = Field(default=None, ge=1)
    funding_interval_minutes: int | None = Field(default=None, ge=0)
    source: str
    fetched_at: datetime
    updated_at: datetime
    age_seconds: float | None = Field(default=None, ge=0)
    ttl_seconds: int | None = Field(default=None, ge=0)
    is_stale: bool = False
