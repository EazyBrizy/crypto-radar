import unittest
from datetime import datetime, timezone

from app.domain.signal_status import (
    can_signal_enter_now,
    is_execution_candidate_status,
    is_market_opportunity_status,
    is_terminal_signal_status,
    is_waiting_entry_status,
)
from app.models.signal import TradingSignal
from app.repositories.signal_repository import (
    PostgresSignalRepository,
    _api_status_to_db,
    _strategy_signal_status_to_db,
)
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    RadarSignal,
    SignalConfirmationSnapshot,
    SignalTriggerSnapshot,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import TradePlanCompletenessResult, build_trade_plan_from_legacy_fields
from app.services.risk_reward_assessment import RiskRewardAssessment
from app.services.signal_status_resolver import SignalStatusResolver


class SignalStatusContractTest(unittest.IsolatedAsyncioTestCase):
    def test_active_is_market_opportunity_but_not_execution_candidate(self) -> None:
        self.assertTrue(is_market_opportunity_status("active"))
        self.assertTrue(is_waiting_entry_status("active"))
        self.assertFalse(is_execution_candidate_status("active"))
        active = _signal(status="active", can_enter=True)
        self.assertFalse(
            can_signal_enter_now(
                active.status,
                decision=active.decision,
                can_enter=active.can_enter,
            )
        )
        self.assertFalse(
            can_signal_enter_now(
                "active",
                can_enter=True,
                decision={
                    "signal_actionable": True,
                    "execution_allowed_virtual": True,
                    "execution_allowed_real": True,
                    "blockers": [],
                },
            )
        )

    def test_entry_touched_and_actionable_are_consistent_execution_candidates(self) -> None:
        self.assertTrue(is_execution_candidate_status("entry_touched"))
        self.assertTrue(is_execution_candidate_status("actionable"))
        self.assertTrue(is_execution_candidate_status("confirmed"))
        for status in ("entry_touched", "actionable"):
            signal = _signal(status=status, can_enter=True)
            self.assertTrue(
                can_signal_enter_now(
                    signal.status,
                    decision=signal.decision,
                    can_enter=signal.can_enter,
                )
            )

            denied_signal = _signal(status=status, can_enter=False)
            self.assertFalse(
                can_signal_enter_now(
                    denied_signal.status,
                    decision=denied_signal.decision,
                    can_enter=denied_signal.can_enter,
                )
            )
            self.assertTrue(
                can_signal_enter_now(
                    status,
                    decision={
                        "signal_actionable": True,
                        "execution_allowed_virtual": True,
                        "execution_allowed_real": True,
                        "blockers": [],
                    },
                    can_enter=None,
                )
            )

    def test_invalidated_and_expired_are_terminal(self) -> None:
        self.assertTrue(is_terminal_signal_status("invalidated"))
        self.assertTrue(is_terminal_signal_status("expired"))
        self.assertTrue(is_terminal_signal_status("rejected"))
        self.assertFalse(is_market_opportunity_status("invalidated"))
        self.assertFalse(is_market_opportunity_status("expired"))
        self.assertFalse(is_market_opportunity_status("rejected"))
        self.assertFalse(is_terminal_signal_status("blocked"))

    def test_trading_signal_db_status_allows_rejected_but_not_blocked(self) -> None:
        status_constraint = next(
            constraint
            for constraint in TradingSignal.__table__.constraints
            if constraint.name == "ck_trading_signals_status"
        )
        constraint_sql = str(status_constraint.sqltext)

        self.assertIn("'rejected'", constraint_sql)
        self.assertNotIn("'blocked'", constraint_sql)

    def test_repository_status_mapping_preserves_rejected(self) -> None:
        self.assertEqual(_api_status_to_db("rejected"), "rejected")
        self.assertEqual(_strategy_signal_status_to_db("rejected", 90), "rejected")

    def test_reject_signal_uses_rejected_terminal_status(self) -> None:
        repo = _CapturingRepository()

        repo.reject_signal("sig_1", note="duplicate")

        self.assertEqual(repo.transition_kwargs["new_status"], "rejected")
        self.assertEqual(repo.transition_kwargs["event_type"], "signal.rejected")

    def test_hard_no_trade_filter_resolves_to_rejected_not_invalidated(self) -> None:
        decision = SignalStatusResolver().resolve(
            signal=_strategy_signal(status="active"),
            params={},
            quality=MarketQualitySnapshot(),
            regime=MarketRegimeSnapshot(),
            confirmation=SignalConfirmationSnapshot(passed=True),
            setup=StrategySetupSnapshot(name="test", stage="confirmed"),
            risk_reward=_risk_reward(passed=True),
            no_trade_filter=NoTradeFilterResult(
                blocked=True,
                hard_block=True,
                blockers=["Scheduled news event"],
            ),
            completeness=TradePlanCompletenessResult(
                complete=True,
                has_entry=True,
                has_structural_stop=True,
                has_structural_target=True,
            ),
            trade_plan=build_trade_plan_from_legacy_fields(
                entry_min=100.0,
                entry_max=101.0,
                stop_loss=98.0,
                take_profit_1=104.0,
                risk_reward=2.0,
            ),
            candle_state="closed",
            production_mode=False,
            actionable_score=70,
            trigger=SignalTriggerSnapshot(passed=True),
        )

        self.assertEqual(decision.status, "rejected")
        self.assertIn("Scheduled news event", decision.status_reason)

def _signal(
    *,
    status: str,
    can_enter: bool | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=f"sig_{status}",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        status=status,
        score=80,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        risk_reward=3.0,
        can_enter=can_enter,
        created_at=now,
        updated_at=now,
    )


class _CapturingRepository(PostgresSignalRepository):
    def __init__(self) -> None:
        self.transition_kwargs: dict[str, object] = {}

    def _transition_signal(self, signal_id: str, **kwargs):  # type: ignore[no-untyped-def]
        self.transition_kwargs = {"signal_id": signal_id, **kwargs}
        return None


def _strategy_signal(*, status: str) -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        direction="LONG",
        confidence=0.82,
        timestamp=int(datetime(2026, 6, 6, tzinfo=timezone.utc).timestamp()),
        score=82,
        status=status,
    )


def _risk_reward(*, passed: bool) -> RiskRewardAssessment:
    return RiskRewardAssessment(
        passed=passed,
        rr=2.0 if passed else None,
        min_rr=1.5,
        guard_mode="hard",
        status="passed" if passed else "failed",
        meets_min_rr=passed,
        blocked=not passed,
        warning=False,
        warning_reason=None,
        block_reason=None if passed else "RR failed",
        target_key="final",
        target_label="final",
        first_target_rr=1.0,
        final_target_rr=2.0,
        reason="RR passed" if passed else "RR failed",
    )


if __name__ == "__main__":
    unittest.main()
