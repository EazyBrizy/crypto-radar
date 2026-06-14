from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from typing import Any
from uuid import UUID

from app.schemas.backtest import BacktestRunRequest, BacktestRunResult
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.services.backtest_runner import BacktestDetailedRunResult, ProductionBacktestRunner
from app.services.historical_candle_provider import InMemoryHistoricalCandleProvider
from app.services.strategy_testing.runner import StrategyTestScenarioRunner
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest
from app.strategies.common import build_signal


@dataclass(frozen=True)
class _SignalSpec:
    direction: str = "LONG"
    score: int = 80
    stop_distance: float = 10.0
    target_distance: float = 20.0
    status: str = "actionable"


class _RecordingFeatureEngine:
    def process_candles(self, candles: list[OHLCVCandle]) -> Features:
        latest = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None
        return Features(
            exchange=latest.exchange,
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            timestamp=latest.close_time,
            price=latest.close,
            open=latest.open,
            high=latest.high,
            low=latest.low,
            close=latest.close,
            price_change_1m=0.0,
            previous_open=previous.open if previous is not None else None,
            previous_high=previous.high if previous is not None else None,
            previous_low=previous.low if previous is not None else None,
            previous_close=previous.close if previous is not None else None,
            previous_volume=previous.volume if previous is not None else None,
            volume=latest.volume,
            volume_spike=1.0,
            volume_ma_20=latest.volume,
            volatility=1.0,
            history_length=len(candles),
            atr_14=1.0,
        )


class _PlannedSignalEngine:
    def __init__(self, plan: dict[int, list[_SignalSpec]]) -> None:
        self._plan = plan

    async def generate_signals(self, features: Features, **_: object):
        result = []
        for spec in self._plan.get(features.timestamp, []):
            entry = features.close
            if spec.direction == "LONG":
                stop_loss = entry - spec.stop_distance
                take_profit_1 = entry + spec.target_distance / 2
                take_profit_2 = entry + spec.target_distance
            else:
                stop_loss = entry + spec.stop_distance
                take_profit_1 = entry - spec.target_distance / 2
                take_profit_2 = entry - spec.target_distance
            signal = build_signal(
                features=features,
                strategy="volatility_squeeze_breakout",
                direction=spec.direction,  # type: ignore[arg-type]
                reasons=["planned test signal"],
                score=spec.score,
                entry=entry,
                stop_loss=stop_loss,
                take_profit_1=take_profit_1,
                take_profit_2=take_profit_2,
            )
            result.append(signal.model_copy(update={"status": spec.status}))
        return result


class _RecordingBacktestRunner:
    def __init__(self) -> None:
        self.requests: list[BacktestRunRequest] = []
        self.modes: list[str] = []

    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BacktestDetailedRunResult:
        _ = kwargs
        self.requests.append(request)
        self.modes.append(mode)
        return BacktestDetailedRunResult(
            run_result=BacktestRunResult(status="completed", result=None),
            trades=[],
            signals_seen=0,
            risk_rejections=0,
            execution_rejections=0,
            assumptions=options or {},
        )


class StrategyTestSignalSelectionTest(unittest.TestCase):
    def test_first_actionable_keeps_old_behavior(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={candles[3].close_time: [_SignalSpec(score=80), _SignalSpec(score=95)]},
            params={"signal_selection_policy": "first_actionable"},
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].signal_score, 80.0)

    def test_entry_touched_status_is_selected_when_position_constraints_allow(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={candles[3].close_time: [_SignalSpec(score=80, status="entry_touched")]},
            params={"signal_selection_policy": "first_actionable"},
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].signal_score, 80.0)

    def test_highest_score_chooses_highest_actionable_signal(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={candles[3].close_time: [_SignalSpec(score=80), _SignalSpec(score=95)]},
            params={"signal_selection_policy": "highest_score"},
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].signal_score, 95.0)

    def test_all_signals_opens_multiple_positions_when_capacity_allows(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={
                candles[3].close_time: [
                    _SignalSpec(score=80),
                    _SignalSpec(score=85),
                    _SignalSpec(score=90),
                ]
            },
            params={
                "signal_selection_policy": "all_signals",
                "max_concurrent_positions": 3,
                "max_positions_per_symbol": 3,
            },
        )

        self.assertEqual(len(detailed.trades), 3)
        self.assertEqual([trade.signal_score for trade in detailed.trades], [80.0, 85.0, 90.0])

    def test_all_non_overlapping_blocks_duplicate_direction_while_open(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={
                candles[3].close_time: [_SignalSpec(score=80)],
                candles[4].close_time: [_SignalSpec(score=85)],
            },
            params={
                "signal_selection_policy": "all_non_overlapping",
                "max_concurrent_positions": 3,
                "max_positions_per_symbol": 3,
            },
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].signal_score, 80.0)

    def test_opposite_signal_is_blocked_when_flip_disabled(self) -> None:
        candles = _candles()
        detailed = _run_signal_selection(
            candles=candles,
            plan={
                candles[3].close_time: [_SignalSpec(direction="LONG", score=80)],
                candles[4].close_time: [_SignalSpec(direction="SHORT", score=90)],
            },
            params={
                "signal_selection_policy": "all_signals",
                "max_concurrent_positions": 2,
                "max_positions_per_symbol": 2,
                "allow_opposite_signal_flip": False,
            },
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].direction, "long")

    def test_cooldown_bars_after_close_prevents_immediate_reentry(self) -> None:
        candles = _candles(stop_out_index=4)
        detailed = _run_signal_selection(
            candles=candles,
            plan={
                candles[3].close_time: [_SignalSpec(score=80, stop_distance=1.0, target_distance=4.0)],
                candles[4].close_time: [_SignalSpec(score=90)],
            },
            params={
                "signal_selection_policy": "all_signals",
                "max_concurrent_positions": 2,
                "max_positions_per_symbol": 2,
                "cooldown_bars_after_close": 1,
            },
        )

        self.assertEqual(len(detailed.trades), 1)
        self.assertEqual(detailed.trades[0].signal_score, 80.0)
        self.assertEqual(detailed.trades[0].close_reason, "stop_loss")

    def test_strategy_test_research_defaults_to_non_overlapping_policy(self) -> None:
        backtest_runner = _RecordingBacktestRunner()
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)  # type: ignore[arg-type]
        request = _strategy_test_request(mode="research_virtual")

        scenario_runner.run_scenario(
            run_id=UUID("11111111-1111-4111-8111-111111111111"),
            user_id=UUID("22222222-2222-4222-8222-222222222222"),
            request=request,
            strategy="volatility_squeeze_breakout",
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )

        params = backtest_runner.requests[0].params
        self.assertEqual(params["signal_selection_policy"], "all_non_overlapping")
        self.assertEqual(params["max_concurrent_positions"], 10)
        self.assertEqual(params["max_positions_per_symbol"], 1)

    def test_strategy_test_production_like_keeps_legacy_defaults(self) -> None:
        backtest_runner = _RecordingBacktestRunner()
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)  # type: ignore[arg-type]
        request = _strategy_test_request(mode="production_like")

        scenario_runner.run_scenario(
            run_id=UUID("11111111-1111-4111-8111-111111111111"),
            user_id=UUID("22222222-2222-4222-8222-222222222222"),
            request=request,
            strategy="volatility_squeeze_breakout",
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )

        params = backtest_runner.requests[0].params
        self.assertEqual(params["signal_selection_policy"], "first_actionable")
        self.assertEqual(params["max_concurrent_positions"], 1)

    def test_strategy_test_defaults_do_not_override_explicit_params(self) -> None:
        backtest_runner = _RecordingBacktestRunner()
        scenario_runner = StrategyTestScenarioRunner(backtest_runner)  # type: ignore[arg-type]
        request = _strategy_test_request(mode="research_virtual").model_copy(
            update={
                "params": {
                    "signal_selection_policy": "highest_score",
                    "max_concurrent_positions": 4,
                    "max_positions_per_symbol": 2,
                }
            }
        )

        scenario_runner.run_scenario(
            run_id=UUID("11111111-1111-4111-8111-111111111111"),
            user_id=UUID("22222222-2222-4222-8222-222222222222"),
            request=request,
            strategy="volatility_squeeze_breakout",
            pair=request.pairs[0],
            timeframe=request.timeframes[0],
        )

        params = backtest_runner.requests[0].params
        self.assertEqual(params["signal_selection_policy"], "highest_score")
        self.assertEqual(params["max_concurrent_positions"], 4)
        self.assertEqual(params["max_positions_per_symbol"], 2)


def _run_signal_selection(
    *,
    candles: list[OHLCVCandle],
    plan: dict[int, list[_SignalSpec]],
    params: dict[str, Any],
) -> BacktestDetailedRunResult:
    runner = ProductionBacktestRunner(
        feature_engine=_RecordingFeatureEngine(),  # type: ignore[arg-type]
        strategy_engine=_PlannedSignalEngine(plan),  # type: ignore[arg-type]
        historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
    )
    request_params = {
        "warmup_candles": 3,
        "rolling_window_candles": 3,
        "risk_settings": {
            "min_rr_ratio": 0,
            "max_price_deviation_bps": 10_000,
            "max_open_risk_percent": 100,
            "futures_max_open_risk_percent": 100,
            "max_correlated_risk_percent": 100,
            "max_daily_loss_percent": 50,
        },
    }
    request_params.update(params)
    return runner.run_detailed(
        BacktestRunRequest(
            user_id="demo_user",
            strategy_code="breakout",
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1m",
            start_at=datetime.fromtimestamp(candles[0].open_time / 1000, tz=timezone.utc),
            end_at=datetime.fromtimestamp(candles[-1].close_time / 1000, tz=timezone.utc),
            initial_capital=Decimal("10000"),
            fee_rate=Decimal("0"),
            slippage_bps=Decimal("0"),
            params=request_params,
        ),
        mode="production_like",
    )


def _candles(*, stop_out_index: int | None = None) -> list[OHLCVCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[OHLCVCandle] = []
    for index in range(8):
        open_time = int((start + timedelta(minutes=index)).timestamp() * 1000)
        high = 100.2
        low = 99.8
        if stop_out_index == index:
            low = 98.5
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=open_time,
                close_time=open_time + 59_999,
                open=100.0,
                high=high,
                low=low,
                close=100.0,
                volume=1000 + index,
                trades=10,
                is_closed=True,
            )
        )
    return candles


def _strategy_test_request(*, mode: str) -> StrategyTestRunRequest:
    start_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return StrategyTestRunRequest(
        user_id="demo_user",
        strategies=["volatility_squeeze_breakout"],
        pairs=[StrategyTestPair(exchange="bybit", symbol="BTCUSDT")],
        timeframes=["1m"],
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        mode=mode,  # type: ignore[arg-type]
        initial_capital=Decimal("10000"),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
        params={},
    )


if __name__ == "__main__":
    unittest.main()
