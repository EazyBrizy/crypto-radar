import unittest

from app.schemas.market import Features
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanEntry,
    TradePlanInvalidation,
    TradePlanTarget,
)
from app.services.trade_plan_completeness import TradePlanCompletenessCheck
from app.strategies.common import build_signal


class TradePlanCompletenessCheckTest(unittest.TestCase):
    def test_build_signal_fallback_stop_and_targets_are_marked(self) -> None:
        signal = build_signal(
            features=_features(),
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            reasons=["Fallback provenance test"],
            score=80,
            entry=100.0,
        )

        self.assertIsNotNone(signal.trade_plan)
        assert signal.trade_plan is not None
        result = TradePlanCompletenessCheck().evaluate(signal.trade_plan)

        self.assertFalse(result.complete)
        self.assertTrue(result.fallback_used)
        self.assertTrue(result.fallback_stop_used)
        self.assertTrue(result.fallback_targets_used)
        self.assertEqual(signal.trade_plan.metadata.get("fallback_stop_source"), "atr")
        self.assertEqual(signal.trade_plan.metadata.get("fallback_target_source"), "r_multiple")
        self.assertEqual(signal.trade_plan.targets[0].source, "r_multiple_fallback")
        self.assertIn("structural_stop", result.missing)

    def test_structural_plan_passes_completeness(self) -> None:
        result = TradePlanCompletenessCheck().evaluate(_structural_plan())

        self.assertTrue(result.complete)
        self.assertTrue(result.has_structural_stop)
        self.assertTrue(result.has_invalidation_thesis)
        self.assertTrue(result.has_structural_target)
        self.assertEqual(result.missing, [])

    def test_fallback_stop_keeps_production_plan_incomplete(self) -> None:
        plan = _structural_plan().model_copy(
            update={
                "metadata": {
                    "fallback_used": True,
                    "fallback_stop_used": True,
                    "fallback_stop_source": "atr",
                }
            },
            deep=True,
        )

        result = TradePlanCompletenessCheck().evaluate(plan)

        self.assertFalse(result.complete)
        self.assertTrue(result.fallback_stop_used)
        self.assertIn("structural_stop", result.missing)

    def test_fallback_targets_keep_production_plan_incomplete(self) -> None:
        plan = _structural_plan().model_copy(
            update={
                "targets": [
                    TradePlanTarget(
                        label="TP1",
                        price=103.0,
                        source="r_multiple_fallback",
                        metadata={"fallback_target_used": True},
                    )
                ],
                "metadata": {
                    "fallback_used": True,
                    "fallback_targets_used": True,
                    "fallback_target_source": "r_multiple",
                },
            },
            deep=True,
        )

        result = TradePlanCompletenessCheck().evaluate(plan)

        self.assertFalse(result.complete)
        self.assertTrue(result.fallback_targets_used)
        self.assertIn("structural_target", result.missing)


def _structural_plan() -> TradePlan:
    return TradePlan(
        entry=TradePlanEntry(price=100.0, min_price=99.9, max_price=100.1, source="structure_zone"),
        stop_loss=98.0,
        targets=[TradePlanTarget(label="TP1", price=104.0, source="range_high")],
        invalidation=TradePlanInvalidation(
            price=98.0,
            hard_stop=98.0,
            conditions=["Close below range reclaim"],
            metadata={"source": "range_reclaim"},
        ),
    )


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1_779_796_800_000,
        price=100.0,
        open=99.8,
        high=100.5,
        low=99.5,
        close=100.0,
        price_change_1m=0.01,
        volume=100.0,
        volume_spike=1.5,
        volume_ma_20=80.0,
        volatility=1.0,
        history_length=120,
        atr_14=1.0,
    )


if __name__ == "__main__":
    unittest.main()
