import unittest
from datetime import datetime, timezone

from app.core.config import settings
from app.schemas.decision import DecisionReason, SignalDecisionSnapshot
from app.schemas.signal import (
    NoTradeFilterResult,
    SignalEdgeSnapshot,
    SignalTriggerSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import build_trade_plan_from_legacy_fields
from app.services.signal_execution_gate import SignalExecutionGateService


class SignalExecutionGateServiceTest(unittest.TestCase):
    def test_actionable_closed_signal_with_positive_edge_passes_execution_gate(self) -> None:
        signal = _signal()

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "passed")
        self.assertEqual(gate.feed_kind, "execution_signal")
        self.assertTrue(gate.can_notify)
        self.assertTrue(gate.can_enter_now)
        self.assertTrue(gate.can_arm_pending)
        self.assertTrue(gate.can_show_in_execution_feed)
        self.assertEqual(gate.reasons, [])

    def test_open_candle_is_never_shown_in_execution_feed(self) -> None:
        signal = _signal(candle_state="open")

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_notify)
        self.assertFalse(gate.can_enter_now)
        self.assertFalse(gate.can_arm_pending)
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("forming_candle", _reason_codes(gate))

    def test_low_score_is_market_idea_not_execution_signal(self) -> None:
        signal = _signal(score=23)

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.feed_kind, "market_idea")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("score_below_execution_threshold", _reason_codes(gate))

    def test_no_trade_hard_block_is_blocked_not_ready(self) -> None:
        signal = _signal(
            no_trade_filter=NoTradeFilterResult(
                blocked=True,
                hard_block=True,
                blockers=["Funding event is too close"],
            )
        )

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("no_trade_hard_block", _reason_codes(gate))

    def test_negative_edge_blocks_execution(self) -> None:
        signal = _signal(edge=_edge("negative", sample_size=80, expectancy=-0.12))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_negative", _reason_codes(gate))

    def test_low_positive_expectancy_blocks_execution(self) -> None:
        signal = _signal(edge=_edge("positive", sample_size=80, expectancy=0.01))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_expectancy_below_threshold", _reason_codes(gate))

    def test_low_profit_factor_blocks_execution(self) -> None:
        signal = _signal(edge=_edge("positive", sample_size=80, expectancy=0.18, profit_factor=1.01))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_profit_factor_below_threshold", _reason_codes(gate))

    def test_high_no_entry_rate_blocks_execution(self) -> None:
        signal = _signal(
            edge=_edge(
                "positive",
                sample_size=80,
                expectancy=0.18,
                profit_factor=1.4,
                metadata={"no_entry_rate": 0.75, "entry_touch_rate": 0.2},
            )
        )

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_entry_touch_rate_below_threshold", _reason_codes(gate))
        self.assertIn("edge_no_entry_rate_above_threshold", _reason_codes(gate))

    def test_insufficient_edge_sample_blocks_execution_by_expectancy_gate(self) -> None:
        signal = _signal(edge=_edge("insufficient_sample", sample_size=8, expectancy=0.2))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_insufficient_sample", _reason_codes(gate))

    def test_unknown_edge_is_not_execution_ready(self) -> None:
        signal = _signal(edge=_edge("unknown", sample_size=0, expectancy=0.0))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_notify)
        self.assertFalse(gate.can_show_in_execution_feed)
        self.assertIn("edge_unknown", _reason_codes(gate))

    def test_wait_for_pullback_is_watchlist(self) -> None:
        signal = _signal(status="wait_for_pullback")

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.feed_kind, "watchlist")
        self.assertFalse(gate.can_notify)
        self.assertFalse(gate.can_enter_now)
        self.assertFalse(gate.can_arm_pending)
        self.assertFalse(gate.can_show_in_execution_feed)

    def test_unconfirmed_trigger_blocks_execution_signal(self) -> None:
        signal = _signal(trigger=SignalTriggerSnapshot(passed=False, reason="Breakout trigger not confirmed"))

        gate = SignalExecutionGateService().evaluate(signal)

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertFalse(gate.can_notify)
        self.assertIn("trigger_not_confirmed", _reason_codes(gate))

    def test_strict_walk_forward_eligibility_blocks_execution_signal(self) -> None:
        previous = settings.execution_require_walk_forward_edge
        settings.execution_require_walk_forward_edge = True
        try:
            signal = _signal(
                edge=_edge(
                    "positive",
                    sample_size=80,
                    expectancy=0.18,
                    metadata={
                        "strategy_eligibility": {
                            "eligible": False,
                            "reason_code": "strategy_eligibility_failed",
                            "reason": "Validation expectancy is below threshold.",
                        }
                    },
                )
            )

            gate = SignalExecutionGateService().evaluate(signal)
        finally:
            settings.execution_require_walk_forward_edge = previous

        self.assertEqual(gate.status, "blocked")
        self.assertEqual(gate.feed_kind, "blocked")
        self.assertIn("strategy_eligibility_failed", _reason_codes(gate))

    def test_strict_gate_uses_persisted_strategy_eligibility_metadata_for_entry_permissions(self) -> None:
        previous = settings.execution_require_walk_forward_edge
        settings.execution_require_walk_forward_edge = True
        try:
            signal = _signal(
                edge=_edge(
                    "positive",
                    sample_size=80,
                    expectancy=0.18,
                    metadata={
                        "strategy_eligibility": {
                            "eligible": False,
                            "reason_code": "strategy_eligibility_failed",
                            "reason": "Historical profile failed expectancy threshold.",
                            "source": "historical_backtest",
                        }
                    },
                )
            )

            gate = SignalExecutionGateService().evaluate(signal)
        finally:
            settings.execution_require_walk_forward_edge = previous

        self.assertFalse(gate.can_enter_now)
        self.assertFalse(gate.can_arm_pending)
        reason = next(item for item in gate.reasons if item.code == "strategy_eligibility_failed")
        self.assertEqual(reason.metadata["source"], "historical_backtest")


def _signal(**overrides) -> StrategySignal:
    trade_plan = build_trade_plan_from_legacy_fields(
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=2.5,
        selected_rr=2.5,
        selected_rr_target="final",
        min_rr_ratio=1.5,
    )
    decision = SignalDecisionSnapshot(
        setup_valid=True,
        trade_plan_valid=True,
        market_context_score=82,
        signal_actionable=True,
        execution_allowed_virtual=True,
        execution_allowed_real=None,
        blockers=[],
        warnings=[],
    )
    payload = {
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "strategy": "trend_pullback_continuation",
        "direction": "LONG",
        "confidence": 0.82,
        "timestamp": int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()),
        "score": 82,
        "timeframe": "15m",
        "candle_state": "closed",
        "status": "actionable",
        "entry_min": 100.0,
        "entry_max": 101.0,
        "stop_loss": 98.0,
        "take_profit_1": 104.0,
        "take_profit_2": 106.0,
        "risk_reward": 2.5,
        "selected_rr": 2.5,
        "selected_rr_target": "final",
        "min_rr_ratio": 1.5,
        "trade_plan": trade_plan,
        "trigger": SignalTriggerSnapshot(passed=True, trigger_type="closed_candle"),
        "edge": _edge("positive", sample_size=80, expectancy=0.18),
        "no_trade_filter": NoTradeFilterResult(blocked=False),
        "decision": decision,
    }
    payload.update(overrides)
    if payload["status"] == "wait_for_pullback":
        payload["decision"] = decision.model_copy(update={"signal_actionable": False})
    return StrategySignal(**payload)


def _edge(
    status: str,
    *,
    sample_size: int,
    expectancy: float,
    profit_factor: float | None = 1.4,
    metadata: dict[str, object] | None = None,
) -> SignalEdgeSnapshot:
    return SignalEdgeSnapshot(
        status=status,
        sample_size=sample_size,
        min_sample_size=50,
        expectancy_after_costs_r=expectancy,
        profit_factor=profit_factor,
        confidence_score=0.8,
        source="outcome",
        metadata=metadata or {},
    )


def _reason_codes(gate) -> set[str]:
    return {reason.code for reason in gate.reasons}


def _warning_codes(gate) -> set[str]:
    return {reason.code for reason in gate.warnings}


if __name__ == "__main__":
    unittest.main()
