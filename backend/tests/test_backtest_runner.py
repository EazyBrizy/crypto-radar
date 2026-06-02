from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app.schemas.backtest import BacktestRunRequest
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.services.backtest_runner import ProductionBacktestRunner
from app.services.historical_candle_provider import InMemoryHistoricalCandleProvider
from app.strategies.common import build_signal


class RecordingFeatureEngine:
    def __init__(self) -> None:
        self.windows: list[list[OHLCVCandle]] = []

    def process_candles(self, candles: list[OHLCVCandle]) -> Features:
        self.windows.append(list(candles))
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
            volume_spike=2.0,
            volume_ma_20=latest.volume,
            volatility=1.0,
            history_length=len(candles),
            atr_14=1.0,
        )


class DeterministicStrategyEngine:
    def __init__(self, trigger_timestamp: int) -> None:
        self.trigger_timestamp = trigger_timestamp
        self.feature_timestamps: list[int] = []

    async def generate_signals(self, features: Features, **_: object):
        self.feature_timestamps.append(features.timestamp)
        if features.timestamp != self.trigger_timestamp:
            return []
        signal = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            reasons=["synthetic actionable setup"],
            score=90,
            entry=features.close,
            stop_loss=features.close - 1.0,
            take_profit_1=features.close + 1.0,
            take_profit_2=features.close + 2.0,
        )
        return [signal.model_copy(update={"status": "actionable"})]


class RepeatingStrategyEngine:
    async def generate_signals(self, features: Features, **_: object):
        signal = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            reasons=["synthetic repeating setup"],
            score=90,
            entry=features.close,
            stop_loss=features.close - 10.0,
            take_profit_1=features.close + 10.0,
            take_profit_2=features.close + 20.0,
        )
        return [signal.model_copy(update={"status": "actionable"})]


class AlphaRecordingStrategyEngine:
    def __init__(self) -> None:
        self.seen_alpha_contexts: list[object] = []

    async def generate_signals(self, features: Features, **kwargs: object) -> list[object]:
        self.seen_alpha_contexts.append(kwargs.get("alpha_context"))
        return []


class BreakoutClassifierStrategyEngine:
    def __init__(self, trigger_timestamp: int) -> None:
        self.trigger_timestamp = trigger_timestamp

    async def generate_signals(self, features: Features, **_: object):
        if features.timestamp != self.trigger_timestamp:
            return []
        signal = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            reasons=["synthetic accepted breakout"],
            score=90,
            entry=features.close,
            stop_loss=features.close - 1.0,
            take_profit_1=features.close + 1.0,
            take_profit_2=features.close + 2.0,
        )
        assert signal.trade_plan is not None
        entry = signal.trade_plan.entry.model_copy(
            update={"metadata": {"entry_model": "aggressive_breakout"}}
        )
        trade_plan = signal.trade_plan.model_copy(
            update={
                "entry": entry,
                "metadata": {
                    **signal.trade_plan.metadata,
                    "entry_model": "aggressive_breakout",
                    "accepted_breakout_score": 0.82,
                    "fakeout_risk_score": 0.18,
                },
            },
            deep=True,
        )
        return [signal.model_copy(update={"status": "actionable", "trade_plan": trade_plan})]


class BacktestRunnerTest(unittest.TestCase):
    def test_runner_creates_trade_and_computes_cost_aware_metrics(self) -> None:
        candles = _candles()
        feature_engine = RecordingFeatureEngine()
        runner = ProductionBacktestRunner(
            feature_engine=feature_engine,  # type: ignore[arg-type]
            strategy_engine=DeterministicStrategyEngine(candles[3].close_time),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run(_request(candles))

        self.assertEqual(result.status, "completed")
        assert result.result is not None
        self.assertGreaterEqual(result.result.trades_count, 1)
        self.assertEqual(result.result.metrics["trades_count"], result.result.trades_count)
        self.assertGreater(result.result.metrics["fees_total"], 0)
        self.assertGreater(result.result.metrics["slippage_total"], 0)
        self.assertIn("realized_pnl", result.result.metrics)
        self.assertIn("mfe_r_avg", result.result.metrics)
        self.assertIn("mae_r_avg", result.result.metrics)
        self.assertIn("by_strategy", result.result.metrics)

    def test_runner_does_not_include_future_candles_in_feature_window(self) -> None:
        candles = _candles()
        feature_engine = RecordingFeatureEngine()
        runner = ProductionBacktestRunner(
            feature_engine=feature_engine,  # type: ignore[arg-type]
            strategy_engine=DeterministicStrategyEngine(candles[4].close_time),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        runner.run(_request(candles))

        for window in feature_engine.windows:
            latest_open_time = window[-1].open_time
            self.assertTrue(all(candle.open_time <= latest_open_time for candle in window))
            self.assertEqual(window, sorted(window, key=lambda candle: candle.open_time))

    def test_backtest_uses_closed_candles_only(self) -> None:
        candles = _candles()
        open_preview = candles[-1].model_copy(
            update={
                "open_time": candles[-1].open_time + 60_000,
                "close_time": candles[-1].close_time + 60_000,
                "is_closed": False,
            }
        )
        feature_engine = RecordingFeatureEngine()
        runner = ProductionBacktestRunner(
            feature_engine=feature_engine,  # type: ignore[arg-type]
            strategy_engine=DeterministicStrategyEngine(candles[3].close_time),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider([*candles, open_preview]),
        )

        result = runner.run_detailed(_request([*candles, open_preview]))

        self.assertEqual(result.assumptions["candle_state"], "closed")
        self.assertTrue(feature_engine.windows)
        for window in feature_engine.windows:
            self.assertTrue(all(candle.is_closed for candle in window))
            self.assertNotIn(open_preview.open_time, [candle.open_time for candle in window])
        for trade in result.trades:
            self.assertEqual(trade.features_snapshot.get("candle_state"), "closed")
            self.assertFalse(trade.features_snapshot.get("alpha_context_available"))
            self.assertIn("candle_state=closed", trade.tags)
            self.assertIn("alpha_context_available=false", trade.tags)

    def test_backtest_works_without_alpha_context(self) -> None:
        candles = _candles()
        strategy_engine = AlphaRecordingStrategyEngine()
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=strategy_engine,  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run_detailed(_request(candles))

        self.assertEqual(result.run_result.status, "completed")
        self.assertFalse(result.assumptions["alpha_context_available"])
        self.assertEqual(
            result.assumptions["alpha_context_missing_sources"],
            ["historical_trades", "historical_l2", "historical_derivative_history"],
        )
        self.assertTrue(strategy_engine.seen_alpha_contexts)
        self.assertTrue(all(context is None for context in strategy_engine.seen_alpha_contexts))

    def test_backtest_records_liquidity_sweep_threshold_experiment_params(self) -> None:
        candles = _candles()
        request = _request(candles)
        request = request.model_copy(
            update={
                "strategy_code": "liquidity_sweep_reversal",
                "params": {
                    **request.params,
                    "min_absorption_score": 0.45,
                    "min_cvd_divergence_score": 0.6,
                    "min_target_distance_r": 1.25,
                },
            }
        )
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=AlphaRecordingStrategyEngine(),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run_detailed(request)

        self.assertEqual(
            result.assumptions["liquidity_sweep_threshold_experiment_params"],
            {
                "min_absorption_score": 0.45,
                "min_cvd_divergence_score": 0.6,
                "min_target_distance_r": 1.25,
            },
        )

    def test_backtest_records_breakout_classifier_experiments_and_groups(self) -> None:
        candles = _candles()
        request = _request(candles).model_copy(
            update={
                "params": {
                    **_request(candles).params,
                    "accepted_breakout_min_score": 0.60,
                    "fakeout_risk_max_score": 0.45,
                    "require_oi_expansion": True,
                }
            }
        )
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=BreakoutClassifierStrategyEngine(candles[3].close_time),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run_detailed(request)

        self.assertEqual(
            result.assumptions["breakout_classifier_experiment_params"],
            {
                "accepted_breakout_min_score": 0.60,
                "fakeout_risk_max_score": 0.45,
                "require_oi_expansion": True,
            },
        )
        assert result.run_result.result is not None
        metrics = result.run_result.result.metrics
        self.assertIn("aggressive_breakout", metrics["by_entry_model"])
        self.assertIn("0.75-1.00", metrics["by_accepted_breakout_score_bucket"])
        self.assertIn("0.00-0.24", metrics["by_fakeout_risk_score_bucket"])
        self.assertIn("entry_model=aggressive_breakout", result.trades[0].tags)
        self.assertIn("accepted_breakout_score_bucket=0.75-1.00", result.trades[0].tags)

    def test_backtest_records_exit_policy_experiment_without_changing_entry_policy(self) -> None:
        candles = _candles()
        request = _request(candles).model_copy(
            update={
                "params": {
                    **_request(candles).params,
                    "exit_policy": "structure_runner",
                    "partial_exit_policy": "source_default",
                    "target_sources_enabled": ["previous_day_high", "measured_move"],
                    "allow_r_multiple_fallback": True,
                }
            }
        )
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=DeterministicStrategyEngine(candles[3].close_time),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run_detailed(request)

        self.assertEqual(
            result.assumptions["exit_policy_experiment_params"],
            {
                "exit_policy": "structure_runner",
                "partial_exit_policy": "source_default",
                "target_sources_enabled": ["previous_day_high", "measured_move"],
                "allow_r_multiple_fallback": True,
            },
        )
        assert result.run_result.result is not None
        metrics = result.run_result.result.metrics
        self.assertIn("legacy_fields", metrics["by_entry_model"])
        self.assertIn("structure_runner", metrics["by_exit_policy"])
        self.assertIn("exit_policy=structure_runner", result.trades[0].tags)

    def test_backtest_records_trend_pullback_experiment_params(self) -> None:
        candles = _candles()
        request = _request(candles).model_copy(
            update={
                "strategy_code": "trend_pullback_continuation",
                "params": {
                    **_request(candles).params,
                    "strategy_params": {
                        "require_structural_zone": True,
                        "require_delta_confirmation": True,
                        "max_exhaustion_score": 0.55,
                        "crowded_oi_penalty": 22,
                        "min_htf_target_distance_r": 0.75,
                    },
                },
            }
        )
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=AlphaRecordingStrategyEngine(),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run_detailed(request)

        self.assertEqual(
            result.assumptions["trend_pullback_experiment_params"],
            {
                "require_structural_zone": True,
                "require_delta_confirmation": True,
                "max_exhaustion_score": 0.55,
                "crowded_oi_penalty": 22,
                "min_htf_target_distance_r": 0.75,
            },
        )

    def test_no_data_returns_explicit_error(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        runner = ProductionBacktestRunner(
            historical_candle_provider=InMemoryHistoricalCandleProvider([]),
        )

        with self.assertRaisesRegex(ValueError, "no_historical_data"):
            runner.run(
                BacktestRunRequest(
                    strategy_code="breakout",
                    exchange="bybit",
                    symbol="BTCUSDT",
                    timeframe="1m",
                    start_at=now,
                    end_at=now + timedelta(minutes=10),
                )
            )

    def test_legacy_run_without_params_keeps_single_open_position_default(self) -> None:
        candles = _legacy_default_candles()
        runner = ProductionBacktestRunner(
            feature_engine=RecordingFeatureEngine(),  # type: ignore[arg-type]
            strategy_engine=RepeatingStrategyEngine(),  # type: ignore[arg-type]
            historical_candle_provider=InMemoryHistoricalCandleProvider(candles),
        )

        result = runner.run(
            BacktestRunRequest(
                user_id="demo_user",
                strategy_code="breakout",
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1m",
                start_at=datetime.fromtimestamp(candles[0].open_time / 1000, tz=timezone.utc),
                end_at=datetime.fromtimestamp(candles[-1].close_time / 1000, tz=timezone.utc),
                initial_capital=Decimal("1000"),
                fee_rate=Decimal("0"),
                slippage_bps=Decimal("0"),
                params={},
            )
        )

        self.assertEqual(result.status, "completed")
        assert result.result is not None
        self.assertEqual(result.result.trades_count, 1)


def _request(candles: list[OHLCVCandle]) -> BacktestRunRequest:
    return BacktestRunRequest(
        user_id="demo_user",
        strategy_code="breakout",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1m",
        start_at=datetime.fromtimestamp(candles[0].open_time / 1000, tz=timezone.utc),
        end_at=datetime.fromtimestamp(candles[-1].close_time / 1000, tz=timezone.utc),
        initial_capital=Decimal("1000"),
        fee_rate=Decimal("0.001"),
        slippage_bps=Decimal("5"),
        params={
            "warmup_candles": 3,
            "rolling_window_candles": 3,
            "risk_settings": {
                "min_rr_ratio": 0,
                "max_price_deviation_bps": 1000,
            },
        },
    )


def _candles() -> list[OHLCVCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [100.0, 100.1, 99.9, 100.0, 102.5, 103.0, 103.2, 103.5]
    candles: list[OHLCVCandle] = []
    for index, close in enumerate(closes):
        open_time = int((start + timedelta(minutes=index)).timestamp() * 1000)
        high = close + 0.4
        low = close - 0.4
        if index == 4:
            high = 103.0
            low = 100.2
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=open_time,
                close_time=open_time + 59_999,
                open=close - 0.1,
                high=high,
                low=low,
                close=close,
                volume=100 + index,
                trades=10,
                is_closed=True,
            )
        )
    return candles


def _legacy_default_candles() -> list[OHLCVCandle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[OHLCVCandle] = []
    for index in range(205):
        open_time = int((start + timedelta(minutes=index)).timestamp() * 1000)
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=open_time,
                close_time=open_time + 59_999,
                open=100.0,
                high=100.2,
                low=99.8,
                close=100.0,
                volume=100 + index,
                trades=10,
                is_closed=True,
            )
        )
    return candles


if __name__ == "__main__":
    unittest.main()
