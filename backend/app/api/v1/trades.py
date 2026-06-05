from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.domain.virtual_trade_status import (
    is_active_virtual_trade_status,
    is_terminal_virtual_trade_status,
)
from app.schemas.external_exchange import (
    ExternalExchangeOrderResponse,
    ExternalExchangeTradeResponse,
    RealTradeImportNotReadyResponse,
    RealTradeImportRequest,
    RealTradeImportResult,
)
from app.schemas.trade import (
    CloseMarketTradeRequest,
    CloseMarketTradeResponse,
    CloseVirtualTradeRequest,
    RealConfirmRequest,
    RealExecutionResult,
    TradeInvalidationActionRequest,
    TradeInvalidationActionResponse,
    TradeInvalidationAlert,
    TradeJournalEntry,
    TradeJournalResponse,
    VirtualAccount,
    VirtualSimulationModelInfo,
    VirtualTrade,
    VirtualTradeResponse,
)
from app.services.execution_service import real_execution_service
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import (
    stop_loss_hit_event,
    take_profit_hit_event,
    trade_closed_event,
)
from app.services.real_trade_import_service import RealTradeImportNotReadyError, real_trade_import_service
from app.services.signal_service import signal_service
from app.services.trade_journal_service import trade_journal_service
from app.services.trade_invalidation import trade_invalidation_service
from app.services.virtual_trading import (
    get_virtual_simulation_model_info,
    virtual_trading_service,
)

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeJournalResponse)
async def list_trade_journal(
    mode: Optional[str] = Query(default=None, pattern="^(virtual|real)$"),
    source: Optional[str] = Query(default=None, pattern="^(virtual|real|backtest)$"),
    tag: Optional[str] = None,
    run_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    signal_id: Optional[str] = None,
) -> TradeJournalResponse:
    account = (
        virtual_trading_service.get_virtual_account()
        if source in {None, "virtual"}
        else None
    )
    return TradeJournalResponse(
        trades=trade_journal_service.list_journal(
            mode=mode,
            status=status_filter,
            signal_id=signal_id,
            source=source,
            tag=tag,
            run_id=run_id,
        ),
        account=account,
    )


@router.get("/virtual", response_model=VirtualTradeResponse)
async def list_virtual_trades(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    signal_id: Optional[str] = None,
) -> VirtualTradeResponse:
    return VirtualTradeResponse(
        trades=virtual_trading_service.list_virtual_trades(
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
        trades=virtual_trading_service.list_real_trades(
            status=status_filter,
            signal_id=signal_id,
        ),
        account=None,
    )


@router.post("/real/confirm", response_model=RealExecutionResult)
async def confirm_real_trade(request: RealConfirmRequest) -> RealExecutionResult:
    signal = signal_service.get_signal(request.signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    try:
        result = await real_execution_service.place_order(
            signal,
            request,
            connection_id=request.connection_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if result.status == "risk_failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.model_dump(mode="json"),
        )
    return result


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
    try:
        return real_trade_import_service.list_orders(
            user_id=user_id,
            connection_id=connection_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/real/external-trades", response_model=list[ExternalExchangeTradeResponse])
async def list_external_exchange_trades(
    user_id: str = "demo_user",
    connection_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ExternalExchangeTradeResponse]:
    try:
        return real_trade_import_service.list_trades(
            user_id=user_id,
            connection_id=connection_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/virtual/account", response_model=VirtualAccount)
async def get_virtual_account() -> VirtualAccount:
    return virtual_trading_service.get_virtual_account()


@router.get("/virtual/simulation-model", response_model=VirtualSimulationModelInfo)
async def get_virtual_simulation_model() -> VirtualSimulationModelInfo:
    return get_virtual_simulation_model_info()


@router.get("/{trade_id}/invalidation", response_model=TradeInvalidationAlert)
async def get_trade_invalidation(trade_id: str) -> TradeInvalidationAlert:
    trade = virtual_trading_service.get_virtual_trade(trade_id)
    if trade is not None:
        return trade_invalidation_service.evaluate_trade(trade)
    real_trade = virtual_trading_service.get_real_trade(trade_id)
    if real_trade is not None:
        return trade_invalidation_service.evaluate_trade(real_trade)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Trade is not found",
    )


@router.post("/{trade_id}/invalidation/actions", response_model=TradeInvalidationActionResponse)
async def record_trade_invalidation_action(
    trade_id: str,
    request: TradeInvalidationActionRequest,
) -> TradeInvalidationActionResponse:
    trade = virtual_trading_service.get_virtual_trade(trade_id)
    if trade is None:
        trade = virtual_trading_service.get_real_trade(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade is not found",
        )
    try:
        alert = trade_invalidation_service.record_user_action(
            trade,
            request.action,
            user_id=request.user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TradeInvalidationActionResponse(
        action=request.action,
        alert=alert,
        message=_trade_invalidation_action_message(request.action),
    )


@router.get("/virtual/{trade_id}", response_model=VirtualTrade)
async def get_virtual_trade(trade_id: str) -> VirtualTrade:
    trade = virtual_trading_service.get_virtual_trade(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Виртуальная сделка не найдена",
        )
    return trade


@router.get("/{trade_id}", response_model=TradeJournalEntry)
async def get_trade_journal_entry(trade_id: str) -> TradeJournalEntry:
    trade = trade_journal_service.get_entry(trade_id)
    if trade is not None:
        return trade

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Сделка в журнале не найдена",
    )


@router.post("/{trade_id}/close-market", response_model=CloseMarketTradeResponse)
async def close_market_trade(
    trade_id: str,
    request: CloseMarketTradeRequest,
) -> CloseMarketTradeResponse:
    virtual_trade = virtual_trading_service.get_virtual_trade(trade_id)
    if virtual_trade is not None:
        invalidation_alert = (
            trade_invalidation_service.evaluate_trade(virtual_trade)
            if request.reason == "invalidation"
            else None
        )
        was_open = is_active_virtual_trade_status(virtual_trade.status)
        closed_trade = virtual_trading_service.close_virtual_trade(
            trade_id,
            CloseVirtualTradeRequest(reason=request.reason),
        )
        if closed_trade is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Virtual trade is not found",
            )
        if invalidation_alert is not None:
            try:
                trade_invalidation_service.record_user_action(
                    virtual_trade,
                    "close_market",
                    alert=invalidation_alert,
                )
            except LookupError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        if was_open:
            await _publish_virtual_close_events(closed_trade)
        return CloseMarketTradeResponse(
            mode="virtual",
            status="closed",
            message=_close_market_message(request.reason),
            trade=TradeJournalEntry.model_validate(closed_trade.model_dump()),
        )

    real_trade = virtual_trading_service.get_real_trade(trade_id)
    if real_trade is not None:
        return CloseMarketTradeResponse(
            mode="real",
            status="not_implemented",
            message=(
                "Real market close is not connected yet. "
                "No exchange order was sent and no real trade was changed."
            ),
            trade=real_trade,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Trade is not found",
    )


@router.post("/virtual/{trade_id}/close", response_model=VirtualTrade)
async def close_virtual_trade(
    trade_id: str,
    request: CloseVirtualTradeRequest,
) -> VirtualTrade:
    current_trade = virtual_trading_service.get_virtual_trade(trade_id)
    invalidation_alert = (
        trade_invalidation_service.evaluate_trade(current_trade)
        if current_trade is not None and request.reason == "invalidation"
        else None
    )
    trade = virtual_trading_service.close_virtual_trade(trade_id, request)
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Виртуальная сделка не найдена",
        )
    if current_trade is not None and invalidation_alert is not None:
        try:
            trade_invalidation_service.record_user_action(
                current_trade,
                "close_market",
                alert=invalidation_alert,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await _publish_virtual_close_events(trade)
    return trade


async def _publish_virtual_close_events(trade: VirtualTrade) -> None:
    if not is_terminal_virtual_trade_status(trade.status):
        return
    await realtime_event_broker.publish(trade_closed_event(trade))
    if trade.close_reason == "take_profit":
        await realtime_event_broker.publish(take_profit_hit_event(trade))
    elif trade.close_reason == "stop_loss":
        await realtime_event_broker.publish(stop_loss_hit_event(trade))


def _close_market_message(reason: str) -> str:
    if reason == "invalidation":
        return "Virtual position closed at market because the strategy idea was invalidated."
    return "Virtual position closed at market with exit fees applied."


def _trade_invalidation_action_message(action: str) -> str:
    if action == "keep_stop_loss":
        return "Strategy invalidation prompt dismissed; stop loss remains active."
    if action == "close_market":
        return "Strategy invalidation close-market decision was recorded."
    return "Strategy invalidation prompt dismissed."
