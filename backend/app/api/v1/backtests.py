from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.config import settings
from app.services.current_user import CurrentUserIdentity, current_user_identity_service
from app.services.strategy_testing.schemas import StrategyTestReport

from app.schemas.backtest import (
    BacktestRunRequest,
    BacktestRunResult,
)
from app.services.backtest_service import BacktestService

router = APIRouter(prefix="/backtests", tags=["backtests"])


def get_backtest_service() -> BacktestService:
    return BacktestService()


@router.post(
    "/run",
    response_model=BacktestRunResult,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Backtest input or historical data error"},
    },
)
async def run_backtest(
    request: BacktestRunRequest,
    fastapi_request: Request,
    service: BacktestService = Depends(get_backtest_service),
) -> BacktestRunResult:
    request = request.model_copy(update={"user_id": _current_user(fastapi_request).user_id})
    try:
        return service.run_backtest(request)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/results", response_model=list[StrategyTestReport])
async def list_backtest_results(
    request: Request,
    user_id: str | UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    service: BacktestService = Depends(get_backtest_service),
) -> list[StrategyTestReport]:
    try:
        return service.list_results(user_id=_route_user_id(request, user_id), limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _route_user_id(request: Request, query_user_id: str | UUID | None) -> str:
    current_user = _current_user(request)
    requested_user_id = str(query_user_id) if query_user_id is not None else None
    if requested_user_id is None or requested_user_id == current_user.user_id:
        return current_user.user_id
    if not _is_production_environment():
        return requested_user_id
    raise PermissionError("Cannot access backtest results for another user.")


def _current_user(request: Request) -> CurrentUserIdentity:
    try:
        return current_user_identity_service.resolve_from_request(request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _is_production_environment() -> bool:
    return settings.app_env.strip().lower() in {"prod", "production"}
