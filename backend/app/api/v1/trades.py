from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.trade import (
    CloseVirtualTradeRequest,
    VirtualTrade,
    VirtualTradeResponse,
)
from app.services.trade_service import trade_service

router = APIRouter(prefix="/trades", tags=["trades"])


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


@router.get("/virtual/{trade_id}", response_model=VirtualTrade)
async def get_virtual_trade(trade_id: str) -> VirtualTrade:
    trade = trade_service.get_virtual_trade(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Виртуальная сделка не найдена",
        )
    return trade


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
