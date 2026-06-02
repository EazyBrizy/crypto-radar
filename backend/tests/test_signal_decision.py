import unittest
from datetime import datetime, timezone

from app.repositories.signal_repository import _snapshot_from_signal, _snapshot_from_strategy_signal
from app.schemas.decision import DecisionReason, SignalDecisionSnapshot
from app.schemas.market import Features
from app.schemas.signal import MarketQualitySnapshot, RadarSignal, SignalLayerCheck, StrategySignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount
from app.schemas.trade_plan import TradePlanCompletenessResult
from app.schemas.user import RiskManagementSettings
from app.services.risk_gate import RiskContextService, RiskGateService
from app.services.signal_decision import SignalDecisionService
from app.strategies.common import build_signal, score_breakdown
from app.strategies.pipeline import MarketQualityInput, StrategyEvaluationContext, StrategySignalPipeline


class SignalDecisionTest(unittest.TestCase):
    def test_decision_reason_schema(self) -> None:
        reason = DecisionReason(
            code="risk_reward_guard",
            message="Risk/reward warning",
            source="rr",
            severity="warning",
            scope="virtual",
            metadata={"selected_rr": 1.2},
        )

        payload = reason.model_dump(mode="json")

        self.assertEqual(payload["source"], "rr")
        self.assertEqual(payload["severity"], "warning")
        self.assertEqual(payload["scope"], "virtual")
        self.assertEqual(payload["metadata"]["selected_rr"], 1.2)

    def test_pipeline_attaches_decision_snapshot(self) -> None:
        features = _features()

        signal = StrategySignalPipeline().finalize(
            _candidate(features),
            StrategyEvaluationContext(signal_features=features, context_features=_context_features()),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.decision)
        assert signal.decision is not None
        self.assertTrue(signal.decision.setup_valid)
        self.assertTrue(signal.decision.signal_actionable)
        self.assertEqual(signal.decision.market_context_score, 80)

    def test_rr_fail_creates_rr_blocker_not_hidden_signal(self) -> None:
        features = _features()

        signal = StrategySignalPipeline().finalize(
            _candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_context_features(),
                strategy_params={"min_rr_ratio": 5.0, "rr_guard_mode": "hard"},
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.status, "ready")
        self.assertIsNotNone(signal.decision)
        assert signal.decision is not None
        self.assertTrue(
            any(
                reason.source == "rr" and reason.code == "blocked_by_rr"
                for reason in signal.decision.blockers
            )
        )

    def test_no_trade_creates_no_trade_blocker(self) -> None:
        features = _features()

        signal = StrategySignalPipeline().finalize(
            _candidate(features),
            StrategyEvaluationContext(
                signal_features=features,
                context_features=_context_features(),
                market_quality=MarketQualityInput(volume_24h_quote=50_000_000, spread_bps=84.0),
                strategy_params={
                    "no_trade_filters_enabled": True,
                    "max_spread_bps_for_entry": 25.0,
                },
            ),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertIsNotNone(signal.decision)
        assert signal.decision is not None
        self.assertTrue(any(reason.source == "no_trade" for reason in signal.decision.blockers))

    def test_market_quality_creates_market_quality_reason(self) -> None:
        snapshot = SignalDecisionSnapshot(
            setup_valid=True,
            trade_plan_valid=True,
            market_context_score=10.0,
            signal_actionable=True,
        )
        quality = MarketQualitySnapshot(
            passed=False,
            tier="major",
            score=10,
            checks=[
                SignalLayerCheck(
                    name="candle_history",
                    status="failed",
                    reason="10/60 candles available",
                )
            ],
        )

        decision = SignalDecisionService().merge_market_quality(snapshot, quality)

        self.assertFalse(decision.signal_actionable)
        self.assertEqual(decision.blockers[0].source, "market_quality")
        self.assertEqual(decision.blockers[0].code, "candle_history")

    def test_open_candle_creates_data_blocker(self) -> None:
        features = _features().model_copy(update={"candle_state": "open"})

        signal = StrategySignalPipeline().finalize(
            _candidate(features).model_copy(update={"candle_state": "open", "status": "actionable"}),
            StrategyEvaluationContext(signal_features=features, context_features=_context_features()),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.status, "watchlist")
        self.assertIsNotNone(signal.decision)
        assert signal.decision is not None
        self.assertTrue(
            any(
                reason.source == "data" and reason.code == "forming_candle"
                for reason in signal.decision.blockers
            )
        )
        self.assertFalse(signal.decision.signal_actionable)

    def test_trade_plan_completeness_maps_by_scope(self) -> None:
        snapshot = SignalDecisionSnapshot(
            setup_valid=True,
            trade_plan_valid=False,
            market_context_score=75.0,
            signal_actionable=True,
        )
        completeness = TradePlanCompletenessResult(
            complete=False,
            missing=["structural_stop"],
        )

        research_decision = SignalDecisionService().merge_trade_plan_completeness(
            snapshot,
            completeness,
            production_mode=False,
        )
        production_decision = SignalDecisionService().merge_trade_plan_completeness(
            snapshot,
            completeness,
            production_mode=True,
        )

        self.assertTrue(research_decision.signal_actionable)
        self.assertEqual(research_decision.warnings[0].source, "setup")
        self.assertEqual(research_decision.warnings[0].scope, "discovery")
        self.assertFalse(production_decision.signal_actionable)
        self.assertEqual(production_decision.blockers[0].source, "setup")
        self.assertEqual(production_decision.blockers[0].severity, "blocker")

    def test_repository_snapshot_keeps_unified_decision_separate_from_legacy_decision(self) -> None:
        decision = SignalDecisionSnapshot(
            setup_valid=True,
            trade_plan_valid=True,
            market_context_score=82.0,
            signal_actionable=True,
            blockers=[
                DecisionReason(
                    code="risk_reward_guard",
                    message="RR policy rejected",
                    source="rr",
                    severity="blocker",
                    scope="virtual",
                )
            ],
        )
        strategy_signal = _candidate(_features()).model_copy(update={"decision": decision})
        radar_signal = _radar_signal().model_copy(
            update={
                "decision": decision,
                "decision_mode": "virtual",
                "decision_note": "manual confirm",
            }
        )

        strategy_snapshot = _snapshot_from_strategy_signal(strategy_signal, explanation=None)
        radar_snapshot = _snapshot_from_signal(radar_signal)

        self.assertEqual(strategy_snapshot["decision_snapshot"]["blockers"][0]["source"], "rr")
        self.assertNotIn("decision", strategy_snapshot)
        self.assertEqual(radar_snapshot["decision_snapshot"]["blockers"][0]["scope"], "virtual")
        self.assertEqual(radar_snapshot["decision"]["decision_mode"], "virtual")
        self.assertEqual(radar_snapshot["decision"]["decision_note"], "manual confirm")

    def test_risk_decision_maps_to_decision_snapshot(self) -> None:
        risk_decision = RiskGateService().evaluate(
            context=RiskContextService().build_virtual_context(
                signal=_radar_signal(),
                request=ManualConfirmRequest(size_usd=10_000),
                account=_account(),
                entry_price=100.0,
                open_positions=[],
                requested_notional=10_000,
                stage="pre_execution",
            ),
            risk_settings=RiskManagementSettings(min_rr_ratio=0, stop_loss_mode="structure"),
        )
        snapshot = SignalDecisionSnapshot(
            setup_valid=True,
            trade_plan_valid=True,
            market_context_score=100.0,
            signal_actionable=True,
        )

        decision = SignalDecisionService().merge_risk_decision(snapshot, risk_decision)

        self.assertFalse(decision.execution_allowed_virtual)
        self.assertTrue(any(reason.source == "risk" for reason in decision.blockers))


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1_779_796_800_000,
        price=101.2,
        open=100.6,
        high=101.5,
        low=100.2,
        close=101.2,
        price_change_1m=0.01,
        volume=120.0,
        volume_spike=1.8,
        volume_ma_20=70.0,
        volatility=1.2,
        history_length=120,
        ema_20=99.4,
        ema_50=98.0,
        ema_200=95.0,
        rsi_14=60.0,
        atr_14=1.0,
        atr_sma_50=1.3,
        adx=28.0,
        adx_rising=True,
        bb_width_percentile=12.0,
        donchian_high_20=100.8,
        donchian_low_20=96.2,
        range_20=4.6,
        range_50_average=6.0,
        range_20_atr=4.6,
        swing_high=104.0,
        swing_low=96.0,
        candle_bullish=True,
        upper_wick_ratio=0.1,
        lower_wick_ratio=0.2,
        atr_increasing=True,
    )


def _context_features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp=1_779_796_800_000,
        price=105.0,
        open=103.0,
        high=106.0,
        low=102.0,
        close=105.0,
        price_change_1m=0.01,
        volume=500.0,
        volume_spike=1.3,
        volume_ma_20=420.0,
        volatility=2.0,
        history_length=220,
        ema_20=104.0,
        ema_50=103.0,
        ema_200=100.0,
        rsi_14=61.0,
        atr_14=2.0,
        adx=35.0,
        adx_rising=True,
        candle_bullish=True,
    )


def _candidate(features: Features) -> StrategySignal:
    return build_signal(
        features=features,
        strategy="volatility_squeeze_breakout",
        direction="LONG",
        scoring=score_breakdown(
            trend_score=35,
            volume_score=20,
            volatility_score=20,
            risk_reward_score=15,
        ),
        reasons=["Decision test setup"],
        entry=features.close,
        stop_loss=features.close - 1.0,
        take_profit_1=features.close + 2.0,
        take_profit_2=features.close + 3.0,
    )


def _account() -> VirtualAccount:
    return VirtualAccount(
        user_id="demo_user",
        starting_balance=100,
        balance=100,
        equity=100,
        realized_pnl=0,
        unrealized_pnl=0,
        updated_at=datetime.now(timezone.utc),
    )


def _radar_signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_decision",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.8,
        risk_reward=3.0,
        urgency="medium",
        score=78,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=90.0,
        take_profit_1=120.0,
        take_profit_2=130.0,
        explanation=[],
        risks=[],
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
