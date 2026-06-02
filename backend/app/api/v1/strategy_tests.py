from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status as http_status

from app.services.strategy_testing.schemas import (
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService


router = APIRouter(prefix="/strategy-tests", tags=["strategy-tests"])


def get_strategy_testing_service() -> StrategyTestingService:
    return StrategyTestingService()


@router.post(
    "/runs",
    response_model=StrategyTestRunResponse,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def create_strategy_test_run(
    request: StrategyTestRunRequest,
    background_tasks: BackgroundTasks,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunResponse:
    try:
        run = service.enqueue_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    background_tasks.add_task(service.execute_run, run.run_id, request)
    return run


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


@router.get("/runs/{run_id}/trades", response_model=list[StrategyTestTrade])
async def list_strategy_test_trades(
    run_id: UUID,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestTrade]:
    try:
        return service.list_trades(run_id, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reports", response_model=list[StrategyTestReport])
async def list_strategy_test_reports(
    user_id: str = "demo_user",
    limit: int = Query(default=50, ge=1, le=500),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestReport]:
    try:
        return service.list_reports(user_id=user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reports/{run_id}", response_model=StrategyTestReport)
async def get_strategy_test_report(
    run_id: UUID,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestReport:
    try:
        return service.build_report(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
