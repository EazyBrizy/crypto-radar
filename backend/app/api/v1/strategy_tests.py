from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status

from app.services.strategy_testing.schemas import (
    StrategyTestReportResponse,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTradeResponse,
)
from app.services.strategy_testing.service import StrategyTestingService


router = APIRouter(prefix="/strategy-tests", tags=["strategy-tests"])


def get_strategy_testing_service() -> StrategyTestingService:
    return StrategyTestingService()


@router.post("/runs", response_model=StrategyTestRunResponse)
async def create_strategy_test_run(
    request: StrategyTestRunRequest,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunResponse:
    try:
        return service.create_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs", response_model=list[StrategyTestRunResponse])
async def list_strategy_test_runs(
    user_id: str = "demo_user",
    status: StrategyTestRunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestRunResponse]:
    try:
        return service.list_runs(user_id=user_id, limit=limit, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=StrategyTestRunDetailResponse)
async def get_strategy_test_run(
    run_id: UUID,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunDetailResponse:
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Strategy test run not found")
    return run


@router.get("/runs/{run_id}/trades", response_model=list[StrategyTestTradeResponse])
async def list_strategy_test_trades(run_id: UUID) -> list[StrategyTestTradeResponse]:
    _ = run_id
    return []


@router.get("/reports", response_model=list[StrategyTestReportResponse])
async def list_strategy_test_reports() -> list[StrategyTestReportResponse]:
    return []


@router.get("/reports/{run_id}", response_model=StrategyTestReportResponse)
async def get_strategy_test_report(run_id: UUID) -> StrategyTestReportResponse:
    _ = run_id
    raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Strategy test report not found")
