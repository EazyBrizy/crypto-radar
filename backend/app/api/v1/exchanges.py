from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.services.radar_config_service import SUPPORTED_EXCHANGES
from app.services.market_scanner import DEFAULT_SYMBOLS
from app.schemas.candle import DEFAULT_TIMEFRAMES
from app.schemas.exchange_connection import (
    ExchangeConnectionActionResponse,
    ExchangeConnectionCreateRequest,
    ExchangeFeeRateResponse,
    ExchangeInstrumentRuleResponse,
    ExchangeConnectionResponse,
    ExchangeConnectionUpdateRequest,
)
from app.schemas.external_exchange import (
    RealTradeImportNotReadyResponse,
    RealTradeImportRequest,
    RealTradeImportResult,
)
from app.services.exchange_connection_service import exchange_connection_service
from app.services.exchange_instrument_service import exchange_instrument_rule_service
from app.services.real_trade_import_service import RealTradeImportNotReadyError, real_trade_import_service

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("")
async def list_exchanges() -> dict[str, list[str]]:
    return {
        "supported_exchanges": SUPPORTED_EXCHANGES,
        "supported_symbols": list(DEFAULT_SYMBOLS),
        "supported_timeframes": list(DEFAULT_TIMEFRAMES),
    }


@router.get("/connections", response_model=list[ExchangeConnectionResponse])
async def list_exchange_connections(user_id: str = "demo_user") -> list[ExchangeConnectionResponse]:
    try:
        return exchange_connection_service.list_connections(user_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/connections", response_model=ExchangeConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_exchange_connection(request: ExchangeConnectionCreateRequest) -> ExchangeConnectionResponse:
    try:
        return exchange_connection_service.create_connection(request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/connections/{connection_id}", response_model=ExchangeConnectionResponse)
async def get_exchange_connection(connection_id: str) -> ExchangeConnectionResponse:
    try:
        return exchange_connection_service.get_connection(connection_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.patch("/connections/{connection_id}", response_model=ExchangeConnectionResponse)
async def update_exchange_connection(
    connection_id: str,
    request: ExchangeConnectionUpdateRequest,
) -> ExchangeConnectionResponse:
    try:
        return exchange_connection_service.update_connection(connection_id, request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exchange_connection(connection_id: str) -> Response:
    try:
        exchange_connection_service.delete_connection(connection_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{connection_id}/test", response_model=ExchangeConnectionActionResponse)
async def test_exchange_connection(connection_id: str) -> ExchangeConnectionActionResponse:
    try:
        return exchange_connection_service.test_connection(connection_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/connections/{connection_id}/fees", response_model=list[ExchangeFeeRateResponse])
async def get_exchange_connection_fee_rates(
    connection_id: str,
    category: str = "linear",
    symbol: str | None = None,
) -> list[ExchangeFeeRateResponse]:
    try:
        return exchange_connection_service.get_fee_rates(
            connection_id,
            category=category,
            symbol=symbol,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/instrument-rules", response_model=list[ExchangeInstrumentRuleResponse])
async def list_exchange_instrument_rules(
    exchange_code: str = "bybit",
    category: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
) -> list[ExchangeInstrumentRuleResponse]:
    try:
        return exchange_instrument_rule_service.list_rules(
            exchange_code=exchange_code,
            category=category,
            symbol=symbol,
            limit=limit,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/bybit/instrument-rules/sync", response_model=list[ExchangeInstrumentRuleResponse])
async def sync_bybit_instrument_rules(
    category: str = "linear",
    symbol: str | None = None,
) -> list[ExchangeInstrumentRuleResponse]:
    try:
        return exchange_instrument_rule_service.sync_bybit_rules(
            category=category,
            symbol=symbol,
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/connections/{connection_id}/sync",
    response_model=RealTradeImportResult,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": RealTradeImportNotReadyResponse}},
)
async def sync_exchange_connection_trades(connection_id: str) -> RealTradeImportResult | JSONResponse:
    try:
        return real_trade_import_service.import_connection(RealTradeImportRequest(connection_id=connection_id))
    except RealTradeImportNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
