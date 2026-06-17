from __future__ import annotations

from typing import Any, Protocol

from app.schemas.backtest import BacktestRunRequest, BacktestRunResult
from app.services.strategy_testing.schemas import (
    StrategyTestMode,
    StrategyTestPair,
    StrategyTestReport,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestSameCandlePolicy,
)
from app.services.strategy_testing.service import StrategyTestingService


class StrategyTestingBacktestService(Protocol):
    def enqueue_run(self, request: StrategyTestRunRequest) -> StrategyTestRunResponse:
        ...

    def list_reports(self, user_id: str, limit: int) -> list[StrategyTestReport]:
        ...


class BacktestService:
    """Compatibility adapter for the legacy /backtests routes.

    Historical backtests are owned by Strategy Testing. This class only maps the
    legacy single strategy/pair/timeframe payload onto that canonical pipeline.
    """

    def __init__(
        self,
        strategy_testing_service: StrategyTestingBacktestService | None = None,
    ) -> None:
        self._strategy_testing_service = strategy_testing_service or StrategyTestingService()

    def run_backtest(self, request: BacktestRunRequest) -> BacktestRunResult:
        if request.end_at <= request.start_at:
            raise ValueError("Backtest end_at must be later than start_at")

        run = self._strategy_testing_service.enqueue_run(_strategy_test_request_from_backtest(request))
        return BacktestRunResult(
            status="queued",
            result=None,
            run_id=run.run_id,
            test_type="historical_backtest",
            canonical_endpoint=f"/api/v1/strategy-tests/runs/{run.run_id}",
            report_endpoint=f"/api/v1/strategy-tests/reports/{run.run_id}",
            requested_matrix=run.requested_matrix,
            message=(
                "Compatibility endpoint accepted the run. Historical backtests are executed "
                "by Strategy Testing; read results from the Strategy Testing report endpoint."
            ),
        )

    def list_results(self, *, user_id: str = "demo_user", limit: int = 50) -> list[StrategyTestReport]:
        return self._strategy_testing_service.list_reports(user_id=user_id, limit=limit)


def _strategy_test_request_from_backtest(request: BacktestRunRequest) -> StrategyTestRunRequest:
    params = dict(request.params)
    if request.strategy_version is not None:
        params.setdefault("strategy_version", request.strategy_version)

    return StrategyTestRunRequest(
        user_id=request.user_id,
        test_type="historical_backtest",
        strategies=[request.strategy_code],
        pairs=[StrategyTestPair(exchange=request.exchange, symbol=request.symbol)],
        timeframes=[request.timeframe],
        start_at=request.start_at,
        end_at=request.end_at,
        mode=_strategy_test_mode(params),
        initial_capital=request.initial_capital,
        fee_rate=request.fee_rate,
        slippage_bps=request.slippage_bps,
        same_candle_policy=_same_candle_policy(params),
        params=params,
        metric_set=_string_list(params.get("metric_set")),
        tags=["backtest", "legacy_backtests"],
    )


def _strategy_test_mode(params: dict[str, Any]) -> StrategyTestMode:
    value = params.get("mode")
    if value in {"discovery", "research_virtual", "production_like"}:
        return value
    return "research_virtual"


def _same_candle_policy(params: dict[str, Any]) -> StrategyTestSameCandlePolicy:
    value = params.get("same_candle_policy")
    if value in {
        "conservative_stop_first",
        "target_first",
        "intrabar_unknown",
        "stop_first",
        "ignore_ambiguous",
    }:
        return value
    return "conservative_stop_first"


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


backtest_service = BacktestService()
