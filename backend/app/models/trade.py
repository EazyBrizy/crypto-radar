from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TradeJournalRecord(Base):
    """DB-модель базового Trade Journal для virtual и real trades."""

    __tablename__ = "trade_journal"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)

    exchange: Mapped[str] = mapped_column(String(32), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    strategy: Mapped[str] = mapped_column(String(128), index=True)
    timeframe: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))

    entry_price: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_usd: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    leverage: Mapped[int] = mapped_column(Integer)
    risk_percent: Mapped[float] = mapped_column(Float)

    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[list[float]] = mapped_column(JSON)
    fees: Mapped[float] = mapped_column(Float, default=0)
    slippage_bps: Mapped[float] = mapped_column(Float, default=0)

    status: Mapped[str] = mapped_column(String(16), index=True)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe: Mapped[float] = mapped_column(Float, default=0)
    mae: Mapped[float] = mapped_column(Float, default=0)

    screenshots: Mapped[list[str]] = mapped_column(JSON)
    ai_review: Mapped[str | None] = mapped_column(String, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
