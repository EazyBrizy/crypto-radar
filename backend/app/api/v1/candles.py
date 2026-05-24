from typing import Optional

from fastapi import APIRouter, Query

from app.schemas.candle import CandleResponse, Timeframe
from app.services.candle_service import candle_service

router = APIRouter(prefix="/candles", tags=["candles"])


@router.get("", response_model=CandleResponse)
async def list_candles(
    exchange: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[Timeframe] = None,
    include_open: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
) -> CandleResponse:
    return CandleResponse(
        candles=candle_service.list_candles(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            include_open=include_open,
            limit=limit,
        )
    )
