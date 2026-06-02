import unittest
from datetime import datetime, timezone

from app.schemas.signal import RadarSignal, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanEntry,
    TradePlanInvalidation,
    TradePlanRiskRules,
    TradePlanTarget,
    build_trade_plan_from_legacy_fields,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.risk_reward_assessment import RiskRewardAssessmentService
from app.services.risk_reward_plan import risk_reward_plan_service


class RiskRewardPlanServiceTest(unittest.TestCase):
    def test_long_nearest_uses_first_valid_target(self) -> None:
        result = risk_reward_plan_service.select_rr_target(
            _trade_plan(targets=[_target("TP1", 112), _target("TP2", 130)]),
            "nearest",
            side="long",
        )

        self.assertEqual(result.selected_target_key, "nearest")
        self.assertEqual(result.selected_target.label if result.selected_target else None, "TP1")
        self.assertAlmostEqual(result.rr_value or 0, 1.2)
        self.assertAlmostEqual(result.first_target_rr or 0, 1.2)
        self.assertAlmostEqual(result.final_target_rr or 0, 3.0)

    def test_long_final_uses_last_target(self) -> None:
        plan = build_trade_plan_from_legacy_fields(
            entry_min=100,
            entry_max=100,
            stop_loss=90,
            take_profit_1=112,
            take_profit_2=130,
        )

        result = risk_reward_plan_service.select_rr_target(plan, "final", side="LONG")

        self.assertEqual(result.selected_target_key, "final")
        self.assertEqual(result.selected_target.label if result.selected_target else None, "TP2")
        self.assertAlmostEqual(result.rr_value or 0, 3.0)

    def test_short_nearest_uses_first_valid_target(self) -> None:
        result = risk_reward_plan_service.select_rr_target(
            _trade_plan(
                side_stop=110,
                targets=[_target("TP1", 94), _target("TP2", 80)],
            ),
            "nearest",
            side="short",
        )

        self.assertEqual(result.selected_target_key, "nearest")
        self.assertEqual(result.selected_target.label if result.selected_target else None, "TP1")
        self.assertAlmostEqual(result.rr_value or 0, 0.6)
        self.assertAlmostEqual(result.final_target_rr or 0, 2.0)

    def test_short_final_uses_last_target(self) -> None:
        result = risk_reward_plan_service.select_rr_target(
            _trade_plan(
                side_stop=110,
                targets=[_target("TP1", 94), _target("TP2", 80)],
            ),
            "final",
            side="SHORT",
        )

        self.assertEqual(result.selected_target_key, "final")
        self.assertEqual(result.selected_target.label if result.selected_target else None, "TP2")
        self.assertAlmostEqual(result.rr_value or 0, 2.0)

    def test_missing_target_is_incomplete_and_pipeline_blocks(self) -> None:
        result = risk_reward_plan_service.select_rr_target(
            _trade_plan(targets=[]),
            "final",
            side="long",
        )

        self.assertIsNone(result.rr_value)
        self.assertEqual(result.reason, "missing_target")

        assessment = RiskRewardAssessmentService().assess(
            _strategy_signal(trade_plan=_trade_plan(targets=[])),
            {"min_rr_ratio": 1.5, "rr_target": "final"},
        )

        self.assertFalse(assessment.passed)
        self.assertTrue(assessment.blocked)
        self.assertIn("entry, stop or target is missing", assessment.block_reason or "")

    def test_pipeline_and_risk_gate_use_same_target_basis(self) -> None:
        expected_rr_by_policy = {"nearest": 1.2, "final": 3.0}
        for rr_target, expected_rr in expected_rr_by_policy.items():
            with self.subTest(rr_target=rr_target):
                trade_plan = _trade_plan(
                    targets=[_target("TP1", 112), _target("TP2", 130)],
                    selected_rr_target=rr_target,
                )
                pipeline_assessment = RiskRewardAssessmentService().assess(
                    _strategy_signal(trade_plan=trade_plan),
                    {"min_rr_ratio": 1.5, "rr_target": rr_target},
                )

                decision = RiskGateService().evaluate(
                    context=RiskContextService().build_virtual_context(
                        signal=_radar_signal(trade_plan=trade_plan),
                        request=ManualConfirmRequest(),
                        account=_account(),
                        entry_price=100,
                        open_positions=[],
                        stage="preview",
                    ),
                    risk_settings=RiskManagementSettings(
                        risk_profile="balanced",
                        risk_per_trade_percent=1.0,
                        min_rr_ratio=1.5,
                        max_daily_loss_percent=3.0,
                        max_account_drawdown_percent=10.0,
                        max_open_risk_percent=5.0,
                        stop_loss_mode="structure",
                    ),
                )

                self.assertAlmostEqual(pipeline_assessment.rr or 0, expected_rr)
                self.assertAlmostEqual(decision.risk_check.rr or 0, pipeline_assessment.rr or 0)
                self.assertEqual(decision.take_profit_plan.selected_rr_target, pipeline_assessment.target_key)


def _trade_plan(
    *,
    side_stop: float = 90,
    targets: list[TradePlanTarget],
    selected_rr_target: str | None = None,
) -> TradePlan:
    return TradePlan(
        entry=TradePlanEntry(price=100.0, min_price=100.0, max_price=100.0),
        stop_loss=side_stop,
        targets=targets,
        invalidation=TradePlanInvalidation(
            price=side_stop,
            hard_stop=side_stop,
            conditions=["Test invalidation"],
            metadata={"source": "test"},
        ),
        risk_rules=TradePlanRiskRules(selected_rr_target=selected_rr_target),
    )


def _target(label: str, price: float) -> TradePlanTarget:
    return TradePlanTarget(label=label, price=price, close_percent=50, source="test_structure")


def _strategy_signal(*, trade_plan: TradePlan) -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.8,
        timestamp=1,
        score=90,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        trade_plan=trade_plan,
    )


def _radar_signal(*, trade_plan: TradePlan) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_rr_basis",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        risk_reward=3.0,
        urgency="medium",
        score=90,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        trade_plan=trade_plan,
        created_at=now,
        updated_at=now,
    )


def _account() -> VirtualAccount:
    now = datetime.now(timezone.utc)
    return VirtualAccount(
        user_id="demo_user",
        starting_balance=100,
        balance=100,
        equity=100,
        realized_pnl=0,
        unrealized_pnl=0,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
