from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.backtest import (
    BacktestNotReadyResponse,
    BacktestResultResponse,
    BacktestRunRequest,
    BacktestRunResult,
)
from app.services.backtest_service import BacktestNotReadyError, backtest_service

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post(
    "/run",
    response_model=BacktestRunResult,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Backtest input or historical data error"},
        status.HTTP_501_NOT_IMPLEMENTED: {"model": BacktestNotReadyResponse},
    },
)
async def run_backtest(request: BacktestRunRequest) -> BacktestRunResult | JSONResponse:
    try:
        return backtest_service.run_backtest(request)
    except BacktestNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/results", response_model=list[BacktestResultResponse])
async def list_backtest_results(
    user_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[BacktestResultResponse]:
    return backtest_service.list_results(user_id=user_id, limit=limit)
