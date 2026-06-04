from fastapi import APIRouter, HTTPException, Query, Response, status

from app.schemas.market import MarketUniverseLimit
from app.schemas.watchlist import (
    AlertRuleCreateRequest,
    AlertRuleResponse,
    AlertRuleTestResponse,
    AlertRuleUpdateRequest,
    MarketPairOption,
    WatchlistCreateRequest,
    WatchlistPairCreateRequest,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from app.services.market_universe_service import DEFAULT_SORT
from app.services.notification_service import notification_service
from app.services.watchlist_service import watchlist_service

router = APIRouter(tags=["watchlists"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/market-pairs", response_model=list[MarketPairOption])
async def list_market_pairs(
    exchange: str | None = Query(default=None),
    category: str | None = Query(default=None),
    quote: str | None = Query(default=None),
    limit: MarketUniverseLimit = Query(default="all"),
    search: str | None = Query(default=None),
    sort: str = Query(default=DEFAULT_SORT),
    liquidity_tier: str | None = Query(default=None),
    status_filter: str | None = Query(default="active/trading", alias="status"),
) -> list[MarketPairOption]:
    try:
        return watchlist_service.list_available_pairs(
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


@router.get("/watchlists", response_model=list[WatchlistResponse])
async def list_watchlists(user_id: str = "demo_user") -> list[WatchlistResponse]:
    try:
        return watchlist_service.list_watchlists(user_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/watchlists", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(request: WatchlistCreateRequest) -> WatchlistResponse:
    try:
        return watchlist_service.create_watchlist(request)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/watchlists/default", response_model=WatchlistResponse)
async def get_default_watchlist(user_id: str = "demo_user") -> WatchlistResponse:
    try:
        return watchlist_service.get_default_watchlist(user_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/watchlists/default/pairs", response_model=WatchlistResponse)
async def add_pair_to_default_watchlist(request: WatchlistPairCreateRequest) -> WatchlistResponse:
    try:
        return watchlist_service.add_pair_to_default(request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/watchlists/default/pairs/{pair_id}", response_model=WatchlistResponse)
async def remove_pair_from_default_watchlist(
    pair_id: str,
    user_id: str = Query(default="demo_user"),
) -> WatchlistResponse:
    try:
        return watchlist_service.remove_pair_from_default(pair_id, user_id=user_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/watchlists/{watchlist_id}", response_model=WatchlistResponse)
async def get_watchlist(watchlist_id: str) -> WatchlistResponse:
    try:
        return watchlist_service.get_watchlist(watchlist_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist(
    watchlist_id: str,
    request: WatchlistUpdateRequest,
) -> WatchlistResponse:
    try:
        return watchlist_service.update_watchlist(watchlist_id, request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: str) -> Response:
    try:
        watchlist_service.delete_watchlist(watchlist_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/watchlists/{watchlist_id}/pairs", response_model=WatchlistResponse)
async def add_pair_to_watchlist(
    watchlist_id: str,
    request: WatchlistPairCreateRequest,
) -> WatchlistResponse:
    try:
        return watchlist_service.add_pair(watchlist_id, request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/watchlists/{watchlist_id}/pairs/{pair_id}", response_model=WatchlistResponse)
async def remove_pair_from_watchlist(watchlist_id: str, pair_id: str) -> WatchlistResponse:
    try:
        return watchlist_service.remove_pair(watchlist_id, pair_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/alerts", response_model=list[AlertRuleResponse])
async def list_alert_rules(user_id: str = "demo_user") -> list[AlertRuleResponse]:
    try:
        return watchlist_service.list_alert_rules(user_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/alerts", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(request: AlertRuleCreateRequest) -> AlertRuleResponse:
    try:
        return watchlist_service.create_alert_rule(request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/alerts/{alert_id}", response_model=AlertRuleResponse)
async def get_alert_rule(alert_id: str) -> AlertRuleResponse:
    try:
        return watchlist_service.get_alert_rule(alert_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.patch("/alerts/{alert_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    alert_id: str,
    request: AlertRuleUpdateRequest,
) -> AlertRuleResponse:
    try:
        return watchlist_service.update_alert_rule(alert_id, request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(alert_id: str) -> Response:
    try:
        watchlist_service.delete_alert_rule(alert_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alerts/{alert_id}/test", response_model=AlertRuleTestResponse)
async def test_alert_rule(alert_id: str) -> AlertRuleTestResponse:
    try:
        result = watchlist_service.test_alert_rule(alert_id)
        pair_label = result.alert_rule.pair.symbol if result.alert_rule.pair is not None else "Global"
        notification = await notification_service.create_alert_test_notification(
            user_id=str(result.alert_rule.user_id),
            alert_rule_id=str(result.alert_rule.id),
            title="Alert test",
            body=f"{pair_label} {result.alert_rule.condition_type}",
            payload=result.event,
            channels=result.alert_rule.channels,
        )
        result.event["notification_id"] = str(notification.id)
        return result
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
