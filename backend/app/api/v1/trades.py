from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.external_exchange import (
    ExternalExchangeOrderResponse,
    ExternalExchangeTradeResponse,
    RealTradeImportNotReadyResponse,
    RealTradeImportRequest,
    RealTradeImportResult,
)
from app.schemas.trade import (
    CloseVirtualTradeRequest,
    TradeJournalEntry,
    TradeJournalResponse,
    VirtualAccount,
    VirtualTrade,
    VirtualTradeResponse,
)
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import (
    stop_loss_hit_event,
    take_profit_hit_event,
    trade_closed_event,
)
from app.services.real_trade_import_service import RealTradeImportNotReadyError, real_trade_import_service
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
        ),
        account=trade_service.get_virtual_account(),
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
        ),
        account=None,
    )


@router.post(
    "/real/import",
    response_model=RealTradeImportResult,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": RealTradeImportNotReadyResponse}},
)
async def import_real_trades(request: RealTradeImportRequest) -> RealTradeImportResult | JSONResponse:
    try:
        return real_trade_import_service.import_connection(request)
    except RealTradeImportNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/real/external-orders", response_model=list[ExternalExchangeOrderResponse])
async def list_external_exchange_orders(
    user_id: str = "demo_user",
    connection_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ExternalExchangeOrderResponse]:
    return real_trade_import_service.list_orders(
        user_id=user_id,
        connection_id=connection_id,
        limit=limit,
    )


@router.get("/real/external-trades", response_model=list[ExternalExchangeTradeResponse])
async def list_external_exchange_trades(
    user_id: str = "demo_user",
    connection_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ExternalExchangeTradeResponse]:
    return real_trade_import_service.list_trades(
        user_id=user_id,
        connection_id=connection_id,
        limit=limit,
    )


@router.get("/virtual/account", response_model=VirtualAccount)
async def get_virtual_account() -> VirtualAccount:
    return trade_service.get_virtual_account()


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
    if trade.status == "closed":
        await realtime_event_broker.publish(trade_closed_event(trade))
        if trade.close_reason == "take_profit":
            await realtime_event_broker.publish(take_profit_hit_event(trade))
        elif trade.close_reason == "stop_loss":
            await realtime_event_broker.publish(stop_loss_hit_event(trade))
    return trade
