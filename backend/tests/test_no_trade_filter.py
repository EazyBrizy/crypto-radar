import unittest
from datetime import datetime, timezone

from app.schemas.market import Features
from app.schemas.risk import AccountRiskSnapshot, RiskContext
from app.schemas.signal import (
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    RadarSignal,
    SignalConfirmationSnapshot,
    SignalLayerCheck,
)
from app.schemas.trade import ManualConfirmRequest
from app.schemas.user import RiskManagementSettings
from app.services.no_trade_filter import NoTradeFilterService
from app.services.risk_gate import RiskContextService, RiskGateService
from app.strategies.common import build_signal, score_breakdown


class NoTradeFilterServiceTest(unittest.TestCase):
    def test_high_spread_creates_no_trade_block(self) -> None:
        result = NoTradeFilterService().evaluate(
            signal=_strategy_signal(),
            features=_features(),
            context={"spread_bps": 84.0},
            settings={
                "no_trade_filters_enabled": True,
                "max_spread_bps_for_entry": 25.0,
            },
        )

        self.assertTrue(result.blocked)
        self.assertIn("high_spread", result.metadata["blocker_codes"])
        self.assertIn("Spread 84.0 bps", result.blockers[0])

    def test_nearby_obstacle_creates_no_trade_block(self) -> None:
        signal = _strategy_signal().model_copy(
            update={
                "regime": MarketRegimeSnapshot(
                    checks=[
                        SignalLayerCheck(
                            name="context_resistance",
                            status="warning",
                            reason="1h resistance is 0.40R from entry",
                            metadata={"distance_r": 0.4, "before_tp1": False},
                        )
                    ]
                )
            }
        )

        result = NoTradeFilterService().evaluate(
            signal=signal,
            features=_features(),
            context={},
            settings={
                "no_trade_filters_enabled": True,
                "max_obstacle_distance_r": 1.0,
            },
        )

        self.assertTrue(result.blocked)
        self.assertIn("near_htf_obstacle", result.metadata["blocker_codes"])
        self.assertIn("0.40R", result.blockers[0])

    def test_overextended_candle_creates_no_trade_block(self) -> None:
        signal = _strategy_signal().model_copy(
            update={
                "confirmation": SignalConfirmationSnapshot(
                    passed=True,
                    checks=[
                        SignalLayerCheck(
                            name="overextension_guard",
                            status="warning",
                            score=2.8,
                            reason="Signal candle body is 2.80 ATR; wait for pullback",
                        )
                    ],
                )
            }
        )

        result = NoTradeFilterService().evaluate(
            signal=signal,
            features=_features(),
            context={},
            settings={"no_trade_filters_enabled": True},
        )

        self.assertTrue(result.blocked)
        self.assertIn("overextended_entry", result.metadata["blocker_codes"])
        self.assertIn("2.80 ATR", result.blockers[0])

    def test_real_risk_gate_blocks_no_trade_signal(self) -> None:
        no_trade = NoTradeFilterResult(
            enabled=True,
            blocked=True,
            hard_block=True,
            blockers=["Spread 84.0 bps is above entry limit 25.0 bps"],
            checks=[
                SignalLayerCheck(
                    name="high_spread",
                    status="failed",
                    reason="Spread 84.0 bps is above entry limit 25.0 bps",
                )
            ],
            metadata={"blocker_codes": ["high_spread"]},
        )
        signal = _radar_signal(no_trade_filter=no_trade)
        request = ManualConfirmRequest(
            user_id="demo_user",
            mode="real",
            account_balance=10_000,
            size_usd=100,
        )
        context = RiskContextService().build_real_context(
            signal=signal,
            request=request,
            entry_price=100.0,
            account_snapshot=AccountRiskSnapshot(
                status="fresh",
                fetched_at=datetime.now(timezone.utc),
                account_equity=10_000,
                available_balance=10_000,
                source="exchange",
            ),
            requested_notional=100.0,
            market_data_status="fresh",
            best_bid=99.95,
            best_ask=100.05,
            orderbook_depth_usd=100_000.0,
        )

        decision = RiskGateService().evaluate(
            context=context,
            risk_settings=RiskManagementSettings(
                min_rr_ratio=0,
                real_requires_positive_edge=False,
            ),
        )

        self.assertFalse(decision.can_enter)
        self.assertEqual(decision.status, "failed")
        self.assertIn("Spread 84.0 bps is above entry limit 25.0 bps", decision.blockers)
        self.assertIsInstance(context, RiskContext)


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
        adx=28.0,
        adx_rising=True,
        bb_width_percentile=12.0,
        donchian_high_20=100.8,
        donchian_low_20=96.2,
        candle_bullish=True,
    )


def _strategy_signal():
    features = _features()
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
        reasons=["No-trade test setup"],
        entry=features.close,
        stop_loss=features.close - 1.0,
        take_profit_1=features.close + 2.0,
        take_profit_2=features.close + 3.0,
    )


def _radar_signal(*, no_trade_filter: NoTradeFilterResult) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_no_trade",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="volatility_squeeze_breakout",
        direction="long",
        confidence=0.82,
        risk_reward=3.0,
        urgency="medium",
        score=88,
        timeframe="15m",
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=98.0,
        take_profit_1=104.0,
        take_profit_2=106.0,
        explanation=[],
        risks=[],
        no_trade_filter=no_trade_filter,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
