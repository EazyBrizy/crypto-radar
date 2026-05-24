from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.trade import (
    CloseVirtualTradeRequest,
    TradeJournalEntry,
    TradeJournalResponse,
    VirtualTrade,
    VirtualTradeResponse,
)
from app.services.trade_service import trade_service

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeJournalResponse)
async def list_trade_journal(
    mode: Optional[str] = Query(default=None, pattern="^(virtual|real)$"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    signal_id: Optional[str] = None,
) -> TradeJournalResponse:
    return TradeJournalResponse(
        trades=trade_service.list_trade_journal(
            mode=mode,
            status=status_filter,
            signal_id=signal_id,
        )
    )


@router.get("/virtual", response_model=VirtualTradeResponse)
async def list_virtual_trades(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    signal_id: Optional[str] = None,
) -> VirtualTradeResponse:
    return VirtualTradeResponse(
        trades=trade_service.list_virtual_trades(
            status=status_filter,
            signal_id=signal_id,
        )
    )


@router.get("/real", response_model=TradeJournalResponse)
async def list_real_trades(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    signal_id: Optional[str] = None,
) -> TradeJournalResponse:
    return TradeJournalResponse(
        trades=trade_service.list_real_trades(
            status=status_filter,
            signal_id=signal_id,
        )
    )


@router.get("/virtual/{trade_id}", response_model=VirtualTrade)
async def get_virtual_trade(trade_id: str) -> VirtualTrade:
    trade = trade_service.get_virtual_trade(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Виртуальная сделка не найдена",
        )
    return trade


@router.get("/{trade_id}", response_model=TradeJournalEntry)
async def get_trade_journal_entry(trade_id: str) -> TradeJournalEntry:
    trade = trade_service.get_virtual_trade(trade_id)
    if trade is not None:
        return TradeJournalEntry.model_validate(trade.model_dump())
    real_trade = trade_service.get_real_trade(trade_id)
    if real_trade is not None:
        return real_trade

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Сделка в журнале не найдена",
    )


@router.post("/virtual/{trade_id}/close", response_model=VirtualTrade)
async def close_virtual_trade(
    trade_id: str,
    request: CloseVirtualTradeRequest,
) -> VirtualTrade:
    trade = trade_service.close_virtual_trade(trade_id, request)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Виртуальная сделка не найдена",
        )
    return trade
