from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import DbSession
from app.models.market import MarketPair
from app.schemas.market import (
    MarketUniverseLimit,
    MarketUniversePairResponse,
    MarketUniverseSyncRequest,
    MarketUniverseSyncResponse,
)
from app.services.market_universe_service import DEFAULT_SORT, list_persisted_market_pairs, sync_exchange_universe

router = APIRouter(prefix="/market-universe", tags=["market-universe"])


def _http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/pairs", response_model=list[MarketUniversePairResponse])
async def list_market_universe_pairs(
    session: DbSession,
    exchange: str = Query(default="bybit"),
    category: str = Query(default="linear"),
    quote: str = Query(default="USDT"),
    limit: MarketUniverseLimit = Query(default="top_200"),
    search: str | None = Query(default=None),
    sort: str = Query(default=DEFAULT_SORT),
    liquidity_tier: str | None = Query(default=None),
    status_filter: str | None = Query(default="active/trading", alias="status"),
) -> list[MarketUniversePairResponse]:
    try:
        pairs = list_persisted_market_pairs(
            session,
            exchange=exchange,
            category=category,
            quote=quote,
            limit=limit,
            search=search,
            sort=sort,
            liquidity_tier=liquidity_tier,
            status=status_filter,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    return [_pair_to_response(pair) for pair in pairs]


@router.post("/sync", response_model=MarketUniverseSyncResponse)
async def sync_market_universe(
    request: MarketUniverseSyncRequest,
    session: DbSession,
) -> MarketUniverseSyncResponse:
    try:
        result = sync_exchange_universe(
            session,
            exchange=request.exchange,
            category=request.category,
            quote=request.quote,
            limit=request.limit,
            sort=request.sort,
            persist=request.persist,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    return MarketUniverseSyncResponse(
        exchange=result.exchange,
        category=result.category,
        quote=result.quote,
        requested_limit=result.requested_limit,
        synced_count=result.synced_count,
        total_available_count=result.total_available_count,
        skipped_count=result.skipped_count,
        synced_at=result.synced_at,
        warnings=result.warnings,
    )


def _pair_to_response(pair: MarketPair) -> MarketUniversePairResponse:
    return MarketUniversePairResponse(
        id=pair.id,
        exchange=pair.exchange.code,
        symbol=pair.symbol,
        base_asset=pair.base_asset.symbol,
        quote_asset=pair.quote_asset.symbol,
        status=pair.status,
        category=pair.category,
        market_type=pair.market_type,
        turnover_24h=pair.turnover_24h,
        volume_24h=pair.base_volume_24h,
        last_price=pair.last_price,
        mark_price=pair.mark_price,
        bid_price=pair.bid_price,
        ask_price=pair.ask_price,
        spread_bps=pair.spread_bps,
        funding_rate=pair.funding_rate,
        liquidity_rank=pair.liquidity_rank,
        liquidity_tier=pair.liquidity_tier,
        synced_at=pair.synced_at,
    )
