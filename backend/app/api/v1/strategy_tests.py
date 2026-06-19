import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status as http_status
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.services.current_user import CurrentUserIdentity, current_user_identity_service
from app.services.strategy_testing.schemas import (
    StrategyTestCalibrationResponse,
    StrategyTestActiveRunResponse,
    StrategyTestEstimateResponse,
    StrategyTestFunnelResponse,
    StrategyTestReport,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestSignalEvent,
    StrategyTestTrade,
)
from app.services.strategy_testing.service import StrategyTestingService


router = APIRouter(prefix="/strategy-tests", tags=["strategy-tests"])
logger = logging.getLogger(__name__)


def get_strategy_testing_service() -> StrategyTestingService:
    return StrategyTestingService()


@router.post(
    "/runs",
    response_model=StrategyTestRunResponse,
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def create_strategy_test_run(
    request: StrategyTestRunRequest,
    fastapi_request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunResponse:
    request = _run_request_for_current_user(fastapi_request, request)
    started_at = time.perf_counter()
    request_id = _request_id(fastapi_request)
    scenario_count = _scenario_count(request)
    logger.info(
        "Strategy test run enqueue started request_id=%s test_type=%s scenario_count=%s pairs=%s timeframes=%s strategies=%s",
        request_id,
        request.test_type,
        scenario_count,
        len(request.pairs),
        len(request.timeframes),
        len(request.strategies),
        extra={
            "request_id": request_id,
            "test_type": request.test_type,
            "scenario_count": scenario_count,
            "pairs_count": len(request.pairs),
            "timeframes_count": len(request.timeframes),
            "strategies_count": len(request.strategies),
        },
    )
    try:
        run = service.enqueue_run(request)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    duration_ms = _duration_ms(started_at)
    logger.info(
        "Strategy test run enqueued request_id=%s run_id=%s status=%s test_type=%s scenario_count=%s duration_ms=%.2f",
        request_id,
        run.run_id,
        run.status,
        run.test_type,
        scenario_count,
        duration_ms,
        extra={
            "request_id": request_id,
            "run_id": str(run.run_id),
            "status": run.status,
            "test_type": run.test_type,
            "scenario_count": scenario_count,
            "duration_ms": duration_ms,
        },
    )
    return run


@router.get("/runs/active", response_model=StrategyTestActiveRunResponse)
async def get_active_strategy_test_run(
    request: Request,
    user_id: str | None = Query(default=None),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestActiveRunResponse:
    try:
        return service.get_active_run(user_id=_route_user_id(request, user_id))
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/runs/estimate", response_model=StrategyTestEstimateResponse)
def estimate_strategy_test_run(
    request: StrategyTestRunRequest,
    fastapi_request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestEstimateResponse:
    request = _run_request_for_current_user(fastapi_request, request)
    started_at = time.perf_counter()
    request_id = _request_id(fastapi_request)
    try:
        estimate = service.estimate_run(request)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    duration_ms = _duration_ms(started_at)
    logger.info(
        "Strategy test run estimate completed request_id=%s test_type=%s scenario_count=%s total_bars=%s size=%s duration_ms=%.2f",
        request_id,
        request.test_type,
        estimate.scenario_count,
        estimate.total_bars,
        estimate.size_level,
        duration_ms,
        extra={
            "request_id": request_id,
            "test_type": request.test_type,
            "scenario_count": estimate.scenario_count,
            "total_bars": estimate.total_bars,
            "size_level": estimate.size_level,
            "duration_ms": duration_ms,
        },
    )
    return estimate


@router.get("/runs", response_model=list[StrategyTestRunResponse])
async def list_strategy_test_runs(
    request: Request,
    user_id: str | None = Query(default=None),
    status: StrategyTestRunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestRunResponse]:
    try:
        return service.list_runs(user_id=_route_user_id(request, user_id), limit=limit, status=status)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=StrategyTestRunDetailResponse)
async def get_strategy_test_run(
    run_id: UUID,
    request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunDetailResponse:
    run = service.get_run_for_user(run_id, user_id=_current_user(request).user_id)
    if run is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Strategy test run not found")
    return run


@router.post("/runs/{run_id}/cancel", response_model=StrategyTestRunResponse)
async def cancel_strategy_test_run(
    run_id: UUID,
    request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestRunResponse:
    try:
        return service.cancel_run(run_id, user_id=_current_user(request).user_id)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/runs/{run_id}/calibration", response_model=StrategyTestCalibrationResponse)
async def publish_strategy_test_calibration(
    run_id: UUID,
    request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestCalibrationResponse:
    try:
        return service.publish_calibration(run_id, user_id=_current_user(request).user_id)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/runs/{run_id}/trades", response_model=list[StrategyTestTrade])
async def list_strategy_test_trades(
    run_id: UUID,
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestTrade]:
    try:
        return await run_in_threadpool(
            service.list_trades,
            run_id,
            limit=limit,
            offset=offset,
            user_id=_current_user(request).user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs/{run_id}/signals", response_model=list[StrategyTestSignalEvent])
async def list_strategy_test_signals(
    run_id: UUID,
    request: Request,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestSignalEvent]:
    try:
        return await run_in_threadpool(
            service.list_signal_events,
            run_id,
            limit=limit,
            offset=offset,
            user_id=_current_user(request).user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/runs/{run_id}/funnel", response_model=StrategyTestFunnelResponse)
async def get_strategy_test_funnel(
    run_id: UUID,
    request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> StrategyTestFunnelResponse:
    try:
        return await run_in_threadpool(service.get_funnel, run_id, user_id=_current_user(request).user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reports", response_model=list[StrategyTestReport])
async def list_strategy_test_reports(
    request: Request,
    user_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> list[StrategyTestReport]:
    try:
        return await run_in_threadpool(service.list_reports, user_id=_route_user_id(request, user_id), limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/reports/{run_id}", response_model=StrategyTestReport)
async def get_strategy_test_report(
    run_id: UUID,
    request: Request,
    service: StrategyTestingService = Depends(get_strategy_testing_service),
) -> Response:
    try:
        report = await run_in_threadpool(service.build_report, run_id, user_id=_current_user(request).user_id)
        return Response(content=report.model_dump_json(), media_type="application/json")
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Strategy test report build failed for run_id=%s", run_id)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Strategy test report failed",
        ) from exc


def _run_request_for_current_user(
    fastapi_request: Request,
    request: StrategyTestRunRequest,
) -> StrategyTestRunRequest:
    return request.model_copy(update={"user_id": _current_user(fastapi_request).user_id})


def _route_user_id(request: Request, query_user_id: str | None) -> str:
    current_user = _current_user(request)
    if query_user_id is None or query_user_id == current_user.user_id:
        return current_user.user_id
    if not _is_production_environment():
        return query_user_id
    raise PermissionError("Cannot access strategy tests for another user.")


def _current_user(request: Request) -> CurrentUserIdentity:
    try:
        return current_user_identity_service.resolve_from_request(request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _is_production_environment() -> bool:
    return settings.app_env.strip().lower() in {"prod", "production"}


def _request_id(request: Request) -> str:
    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str) and state_request_id:
        return state_request_id
    return request.headers.get("X-Request-Id", "").strip() or "unknown"


def _scenario_count(request: StrategyTestRunRequest) -> int:
    return len(request.strategies) * len(request.pairs) * len(request.timeframes)


def _duration_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000
