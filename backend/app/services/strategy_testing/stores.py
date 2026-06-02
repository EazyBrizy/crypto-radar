from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.strategy_testing import StrategyTestRun
from app.models.user import AppUser
from app.services.strategy_testing.schemas import (
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
)


DEMO_PUBLIC_USER_ID = "demo_user"
DEMO_USERNAME = "demo"
REQUEST_PARAMS_KEY = "request_params"
INITIAL_CAPITAL_KEY = "initial_capital"
FEE_RATE_KEY = "fee_rate"
SLIPPAGE_BPS_KEY = "slippage_bps"
SAME_CANDLE_POLICY_KEY = "same_candle_policy"


class StrategyTestRunStore(Protocol):
    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        ...

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        ...

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        ...

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        ...


class PostgresStrategyTestRunStore:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, request.user_id)
            now = datetime.now(timezone.utc)
            run = StrategyTestRun(
                id=uuid4(),
                user_id=user.id,
                requested_user_id=request.user_id,
                status="queued",
                mode=request.mode,
                requested_strategies=list(request.strategies),
                requested_pairs=[pair.model_dump(mode="json") for pair in request.pairs],
                requested_timeframes=list(request.timeframes),
                start_at=request.start_at,
                end_at=request.end_at,
                params=_stored_params(request),
                metric_set=list(request.metric_set),
                tags=list(request.tags),
                created_at=now,
            )
            session.add(run)
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with self._session_factory() as session:
            statement = select(StrategyTestRun)
            if user_id is not None:
                user = _resolve_user(session, user_id)
                statement = statement.where(StrategyTestRun.user_id == user.id)
            if status is not None:
                statement = statement.where(StrategyTestRun.status == status)
            statement = statement.order_by(StrategyTestRun.created_at.desc()).limit(limit)
            return [_run_to_detail(run) for run in session.scalars(statement).all()]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        with self._session_factory() as session:
            run = session.get(StrategyTestRun, run_id)
            if run is None:
                return None
            return _run_to_detail(run)

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            run.error = None
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            run.error = None
            session.flush()
            detail = _run_to_detail(run, summary=summary)
            session.commit()
            return detail

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error = error
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail


def _resolve_user(session: Session, user_id: str) -> AppUser:
    value = user_id.strip()
    if not value:
        raise ValueError(f"User is not seeded: {user_id}")

    if value == DEMO_PUBLIC_USER_ID:
        user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).one_or_none()
        if user is not None:
            return user
        raise ValueError(f"User is not seeded: {user_id}")

    user_uuid = _parse_uuid(value)
    if user_uuid is not None:
        user = session.get(AppUser, user_uuid)
        if user is not None:
            return user
        raise ValueError(f"User is not seeded: {user_id}")

    user = session.scalars(
        select(AppUser).where((AppUser.username == value) | (AppUser.email == value))
    ).one_or_none()
    if user is not None:
        return user

    raise ValueError(f"User is not seeded: {user_id}")


def _get_run_or_raise(session: Session, run_id: UUID) -> StrategyTestRun:
    run = session.get(StrategyTestRun, run_id)
    if run is None:
        raise ValueError(f"Strategy test run is not found: {run_id}")
    return run


def _stored_params(request: StrategyTestRunRequest) -> dict[str, Any]:
    dumped = request.model_dump(mode="json")
    return {
        REQUEST_PARAMS_KEY: dumped["params"],
        INITIAL_CAPITAL_KEY: dumped["initial_capital"],
        FEE_RATE_KEY: dumped["fee_rate"],
        SLIPPAGE_BPS_KEY: dumped["slippage_bps"],
        SAME_CANDLE_POLICY_KEY: dumped["same_candle_policy"],
    }


def _run_to_detail(
    run: StrategyTestRun,
    *,
    summary: dict[str, Any] | None = None,
) -> StrategyTestRunDetailResponse:
    return StrategyTestRunDetailResponse(
        run=StrategyTestRunResponse(
            run_id=run.id,
            status=cast(StrategyTestRunStatus, run.status),
            requested_matrix=_requested_matrix(run),
            summary=summary or {},
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
        ),
    )


def _requested_matrix(run: StrategyTestRun) -> dict[str, Any]:
    params = run.params or {}
    request_params = params.get(REQUEST_PARAMS_KEY, params)
    return {
        "user_id": run.requested_user_id,
        "mode": run.mode,
        "strategies": list(run.requested_strategies),
        "pairs": list(run.requested_pairs),
        "timeframes": list(run.requested_timeframes),
        "start_at": run.start_at,
        "end_at": run.end_at,
        "initial_capital": params.get(INITIAL_CAPITAL_KEY),
        "fee_rate": params.get(FEE_RATE_KEY),
        "slippage_bps": params.get(SLIPPAGE_BPS_KEY),
        "same_candle_policy": params.get(SAME_CANDLE_POLICY_KEY),
        "params": request_params,
        "metric_set": list(run.metric_set),
        "tags": list(run.tags),
        "scenario_count": len(run.requested_strategies) * len(run.requested_pairs) * len(run.requested_timeframes),
    }


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None
