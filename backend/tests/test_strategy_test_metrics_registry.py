from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
import unittest

from app.services.strategy_testing.metrics import BASE_METRIC_CODES, MetricResult, build_base_metric_registry
from app.services.strategy_testing.report_builder import build_matrix_metric_results
from app.services.strategy_testing.schemas import StrategyTestSignalEvent, StrategyTestTrade


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


class StrategyTestMetricsRegistryTest(unittest.TestCase):
    def test_registry_contains_all_base_metric_codes(self) -> None:
        registry = build_base_metric_registry()

        codes = {definition.code for definition in registry.list_definitions()}

        self.assertEqual(codes, set(BASE_METRIC_CODES))

    def test_winrate_expectancy_and_profit_factor_are_computed(self) -> None:
        registry = build_base_metric_registry()
        trades = [
            _trade("trade-1", realized_r=2.0),
            _trade("trade-2", realized_r=-1.0),
            _trade("trade-3", realized_r=0.5),
        ]

        results = _results_by_code(
            registry.compute(trades, metric_set=["winrate", "expectancy_r", "profit_factor"])
        )

        self.assertAlmostEqual(results["winrate"].value or 0, 2 / 3)
        self.assertAlmostEqual(results["expectancy_r"].value or 0, 0.5)
        self.assertAlmostEqual(results["profit_factor"].value or 0, 2.5)

    def test_expectancy_after_costs_uses_strategy_test_net_realized_r(self) -> None:
        registry = build_base_metric_registry()
        trades = [
            _trade("trade-1", realized_r=1.2),
            _trade("trade-2", realized_r=-0.4),
        ]

        result = _results_by_code(registry.compute(trades, metric_set=["expectancy_after_costs_r"]))[
            "expectancy_after_costs_r"
        ]

        self.assertAlmostEqual(result.value or 0, 0.4)
        self.assertEqual(result.warnings, [])

    def test_group_by_strategy_symbol_works(self) -> None:
        registry = build_base_metric_registry()
        trades = [
            _trade("trade-1", strategy="s1", symbol="BTCUSDT", realized_r=1.0),
            _trade("trade-2", strategy="s1", symbol="BTCUSDT", realized_r=-1.0),
            _trade("trade-3", strategy="s2", symbol="ETHUSDT", realized_r=1.0),
        ]

        results = registry.compute(trades, metric_set=["trades_count"], group_by=["strategy", "symbol"])

        aggregate = next(result for result in results if result.group == {"all": "all"})
        grouped = {
            (result.group["strategy"], result.group["symbol"]): result.value
            for result in results
            if result.group != {"all": "all"}
        }
        self.assertEqual(aggregate.value, 3)
        self.assertEqual(grouped, {("s1", "BTCUSDT"): 2, ("s2", "ETHUSDT"): 1})

    def test_empty_trades_do_not_crash(self) -> None:
        registry = build_base_metric_registry()

        results = _results_by_code(
            registry.compute([], metric_set=["trades_count", "winrate", "fees_total"])
        )

        self.assertEqual(results["trades_count"].value, 0)
        self.assertIsNone(results["winrate"].value)
        self.assertEqual(results["fees_total"].value, 0.0)

    def test_unknown_metric_set_code_raises_clear_error(self) -> None:
        registry = build_base_metric_registry()

        with self.assertRaisesRegex(ValueError, "Unknown metric code: does_not_exist"):
            registry.compute([], metric_set=["does_not_exist"])

    def test_rejection_rates_are_computed_from_rejected_trade_rows(self) -> None:
        registry = build_base_metric_registry()
        trades = [
            _trade("trade-1", realized_r=1.0),
            _trade("trade-2", realized_r=None, risk_rejected=True),
            _trade("trade-3", realized_r=None, execution_rejected=True),
            _trade("trade-4", realized_r=-1.0),
        ]

        results = _results_by_code(
            registry.compute(trades, metric_set=["risk_rejection_rate", "execution_rejection_rate"])
        )

        self.assertEqual(results["risk_rejection_rate"].value, 0.25)
        self.assertEqual(results["execution_rejection_rate"].value, 0.25)

    def test_funding_total_unavailable_behavior_is_explicit(self) -> None:
        registry = build_base_metric_registry()

        result = _results_by_code(registry.compute([_trade("trade-1")], metric_set=["funding_total"]))[
            "funding_total"
        ]

        self.assertIsNone(result.value)
        self.assertIn("funding_not_modeled", result.warnings)

    def test_matrix_metrics_include_full_eligibility_profile_grouping(self) -> None:
        results = build_matrix_metric_results(
            [
                _trade("trade-1", realized_r=1.0),
                _trade("trade-2", realized_r=-0.5),
            ],
            metric_set=["trades_count", "profit_factor"],
        )

        groups = {tuple(sorted(result.group.items())) for result in results}

        self.assertIn(
            (
                ("direction", "long"),
                ("exchange", "bybit"),
                ("regime", "trend"),
                ("score_bucket", "80-89"),
                ("strategy", "trend_pullback_continuation"),
                ("symbol", "BTCUSDT"),
                ("timeframe", "1h"),
            ),
            groups,
        )

    def test_signal_funnel_metrics_are_computed_from_signal_events(self) -> None:
        results = build_matrix_metric_results(
            [_trade("trade-1", realized_r=1.0)],
            signal_events=[
                _signal_event(
                    "signal-1",
                    entry_touched=True,
                    filled=True,
                    closed=True,
                    outcome="win",
                    funnel_stage="closed",
                ),
                _signal_event(
                    "signal-2",
                    entry_touched=False,
                    no_entry=True,
                    outcome="no_entry",
                    funnel_stage="no_entry",
                ),
                _signal_event(
                    "signal-3",
                    execution_candidate=True,
                    execution_rejected=True,
                    rejection_reason_code="execution_policy_rejected",
                    outcome="rejected",
                    funnel_stage="execution_rejected",
                ),
            ],
            metric_set=[
                "signals_count",
                "entry_touch_rate",
                "no_entry_rate",
                "execution_rejection_rate",
                "false_signal_rate",
                "expectancy_after_costs_r",
            ],
        )

        aggregate = _results_by_code(results)
        self.assertEqual(aggregate["signals_count"].value, 3)
        self.assertEqual(aggregate["signals_count"].warnings, [])
        self.assertAlmostEqual(aggregate["entry_touch_rate"].value or 0, 1 / 3)
        self.assertAlmostEqual(aggregate["no_entry_rate"].value or 0, 1 / 3)
        self.assertAlmostEqual(aggregate["execution_rejection_rate"].value or 0, 1 / 3)
        self.assertAlmostEqual(aggregate["false_signal_rate"].value or 0, 1 / 3)
        self.assertAlmostEqual(aggregate["expectancy_after_costs_r"].value or 0, 1.0)

    def test_signal_only_groups_are_kept_even_without_trades(self) -> None:
        results = build_matrix_metric_results(
            [],
            signal_events=[
                _signal_event("signal-1", strategy="s1", symbol="BTCUSDT", no_entry=True),
                _signal_event("signal-2", strategy="s2", symbol="ETHUSDT", no_entry=True),
            ],
            metric_set=["signals_count", "no_entry_rate"],
        )

        grouped = {
            (result.group.get("strategy"), result.group.get("symbol"), result.code): result.value
            for result in results
            if result.group != {"all": "all"}
        }

        self.assertEqual(grouped[("s1", "BTCUSDT", "signals_count")], 1)
        self.assertEqual(grouped[("s2", "ETHUSDT", "signals_count")], 1)
        self.assertEqual(grouped[("s1", "BTCUSDT", "no_entry_rate")], 1.0)


def _results_by_code(results: list[MetricResult]) -> dict[str, MetricResult]:
    return {result.code: result for result in results if result.group == {"all": "all"}}


def _trade(
    trade_id: str,
    *,
    strategy: str = "trend_pullback_continuation",
    symbol: str = "BTCUSDT",
    realized_r: float | None = 1.0,
    risk_rejected: bool = False,
    execution_rejected: bool = False,
    features_snapshot: dict[str, Any] | None = None,
) -> StrategyTestTrade:
    offset = int(trade_id.rsplit("-", 1)[-1])
    entry_time = NOW + timedelta(hours=offset)
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id=trade_id,
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code=strategy,
        strategy_version="v1",
        exchange="bybit",
        symbol=symbol,
        timeframe="1h",
        direction="long",
        signal_score=80.0,
        market_regime="trend",
        score_bucket="80-89",
        entry_time=entry_time,
        exit_time=entry_time + timedelta(hours=1),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        stop_loss=Decimal("99"),
        targets=[
            {"label": "TP1", "price": "101", "hit": bool(realized_r is not None and realized_r > 0)},
            {"label": "TP2", "price": "102", "hit": False},
        ],
        selected_rr=1.0,
        realized_r=realized_r,
        pnl=Decimal("10") if realized_r is None else Decimal(str(realized_r * 10)),
        pnl_pct=0.01 if realized_r is None else realized_r / 100,
        fees=Decimal("0.1"),
        slippage=Decimal("0.05"),
        mfe_r=realized_r if realized_r is not None and realized_r > 0 else 0.2,
        mae_r=realized_r if realized_r is not None and realized_r < 0 else -0.1,
        bars_to_entry=1,
        bars_in_trade=3,
        close_reason=_close_reason(realized_r, risk_rejected, execution_rejected),
        outcome=_outcome(realized_r, risk_rejected, execution_rejected),
        risk_rejected=risk_rejected,
        execution_rejected=execution_rejected,
        warnings=[],
        features_snapshot=features_snapshot or {},
        trade_plan={},
        tags=["backtest"],
        created_at=entry_time + timedelta(hours=1),
    )


def _signal_event(
    synthetic_signal_id: str,
    *,
    strategy: str = "trend_pullback_continuation",
    symbol: str = "BTCUSDT",
    execution_candidate: bool = True,
    entry_touched: bool = False,
    filled: bool = False,
    closed: bool = False,
    outcome: str | None = None,
    funnel_stage: str = "signal",
    risk_rejected: bool = False,
    execution_rejected: bool = False,
    no_entry: bool = False,
    rejection_reason_code: str | None = None,
) -> StrategyTestSignalEvent:
    return StrategyTestSignalEvent(
        run_id=RUN_ID,
        user_id=USER_ID,
        mode="research_virtual",
        test_type="historical_backtest",
        strategy_code=strategy,
        strategy_version="v1",
        exchange="bybit",
        symbol=symbol,
        timeframe="1h",
        direction="long",
        signal_id=None,
        synthetic_signal_id=synthetic_signal_id,
        signal_key=f"{strategy}:{symbol}:{synthetic_signal_id}",
        event_time=NOW,
        candle_time=NOW,
        signal_score=80.0,
        market_regime="trend",
        score_bucket="80-89",
        status="actionable" if execution_candidate else "watchlist",
        gate_status="passed" if execution_candidate else "blocked",
        feed_kind="execution_signal" if execution_candidate else "watchlist",
        trigger_passed=execution_candidate,
        trigger_reason_code=None,
        execution_candidate=execution_candidate,
        entry_touched=entry_touched,
        filled=filled,
        closed=closed,
        outcome=outcome,
        funnel_stage=funnel_stage,
        risk_rejected=risk_rejected,
        execution_rejected=execution_rejected,
        no_entry=no_entry,
        rejection_reason_code=rejection_reason_code,
        blocked_reason_code=rejection_reason_code,
        selected_rr=2.0,
        entry_min=Decimal("100"),
        entry_max=Decimal("100"),
        stop_loss=Decimal("99"),
        features_snapshot={"source": "test"},
        trade_plan={"entry": {"price": "100"}},
        metadata={},
        tags=["backtest"],
        created_at=NOW,
    )


def _close_reason(
    realized_r: float | None,
    risk_rejected: bool,
    execution_rejected: bool,
) -> str:
    if risk_rejected:
        return "risk_rejected"
    if execution_rejected:
        return "execution_rejected"
    if realized_r is not None and realized_r < 0:
        return "stop_loss"
    return "take_profit"


def _outcome(
    realized_r: float | None,
    risk_rejected: bool,
    execution_rejected: bool,
) -> str:
    if risk_rejected or execution_rejected:
        return "rejected"
    if realized_r is not None and realized_r > 0:
        return "win"
    if realized_r is not None and realized_r < 0:
        return "loss"
    return "breakeven"


if __name__ == "__main__":
    unittest.main()
