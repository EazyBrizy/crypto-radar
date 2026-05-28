import unittest

from app.schemas.market import Features
from app.schemas.signal import SignalScoreBreakdown
from app.strategies.breakout import VolatilitySqueezeBreakoutStrategy
from app.strategies.common import score_breakdown, score_from_breakdown
from backend.tests.ephemeral_signal_service import ephemeral_signal_service


class SignalScoringContractTest(unittest.IsolatedAsyncioTestCase):
    def test_score_breakdown_matches_architecture_formula(self) -> None:
        breakdown = score_breakdown(
            trend_score=25,
            volume_score=20,
            liquidity_score=10,
            orderbook_score=5,
            risk_reward_score=12,
            volatility_score=15,
            overheat_penalty=10,
            news_event_risk_penalty=5,
        )

        self.assertEqual(breakdown.total, 72)
        self.assertEqual(score_from_breakdown(breakdown), 72)

    async def test_strategy_signal_contains_explainable_score(self) -> None:
        features = Features(
            exchange="bybit",
            symbol="BTC/USDT:PERP",
            timeframe="1m",
            timestamp=1_717_000_000_000,
            price=110,
            open=108,
            high=112,
            low=106,
            close=110,
            price_change_1m=0.02,
            volume=200,
            volume_spike=2.0,
            volume_ma_20=100,
            volatility=4,
            history_length=80,
            rsi_14=62,
            atr_14=1,
            bb_width_percentile=10,
            donchian_high_20=105,
            donchian_low_20=90,
            atr_increasing=True,
        )

        signals = await VolatilitySqueezeBreakoutStrategy().evaluate(features)

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertGreaterEqual(signal.score, 70)
        self.assertEqual(signal.score, signal.score_breakdown.total)
        self.assertGreater(signal.score_breakdown.trend_score, 0)
        self.assertGreater(signal.score_breakdown.volume_score, 0)
        self.assertGreater(signal.score_breakdown.volatility_score, 0)
        self.assertGreater(signal.score_breakdown.risk_reward_score, 0)
        self.assertTrue(signal.explanation)

    async def test_radar_signal_preserves_score_breakdown(self) -> None:
        features = Features(
            symbol="ETH/USDT:PERP",
            timestamp=1_717_000_000_000,
            price=100,
            open=99,
            high=102,
            low=98,
            close=100,
            price_change_1m=0.01,
            volume=100,
            volume_spike=2.0,
            volume_ma_20=75,
            volatility=2,
            history_length=80,
        )
        scoring = SignalScoreBreakdown(
            trend_score=40,
            volume_score=20,
            liquidity_score=0,
            orderbook_score=0,
            risk_reward_score=15,
            volatility_score=10,
            overheat_penalty=0,
            news_event_risk_penalty=0,
            total=85,
        )
        signal = await VolatilitySqueezeBreakoutStrategy().evaluate(
            features.model_copy(
                update={
                    "bb_width_percentile": 10,
                    "donchian_high_20": 95,
                    "atr_14": 1,
                    "atr_increasing": True,
                }
            )
        )
        self.assertTrue(signal)

        stored = ephemeral_signal_service().add_strategy_signal(
            signal[0].model_copy(update={"score_breakdown": scoring, "score": 85})
        )

        self.assertEqual(stored.score, 85)
        self.assertEqual(stored.score_breakdown.total, 85)


if __name__ == "__main__":
    unittest.main()
