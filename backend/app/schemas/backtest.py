from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    user_id: str = "demo_user"
    strategy_code: str = Field(..., min_length=1)
    strategy_version: str | None = None
    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    timeframe: str = Field(..., min_length=1)
    start_at: datetime
    end_at: datetime
    initial_capital: Decimal = Field(default=Decimal("1000"), gt=0)
    fee_rate: Decimal = Field(default=Decimal("0.001"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0)
    params: dict[str, Any] = Field(default_factory=dict)


class BacktestResultResponse(BaseModel):
    run_id: UUID
    user_id: UUID
    strategy_code: str
    strategy_version: str
    exchange: str
    symbol: str
    timeframe: str
    start_at: datetime
    end_at: datetime
    initial_capital: Decimal
    final_equity: Decimal
    pnl: Decimal
    pnl_pct: float
    max_drawdown_pct: float
    trades_count: int
    wins_count: int
    losses_count: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class BacktestRunResult(BaseModel):
    status: Literal["completed", "queued"]
    result: BacktestResultResponse | None = None
    run_id: UUID | None = None
    test_type: Literal["historical_backtest"] | None = None
    canonical_endpoint: str | None = None
    report_endpoint: str | None = None
    requested_matrix: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
