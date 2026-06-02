import unittest

from app.schemas.market import AlphaMarketContext, Features, LiquidityPoolFeatures
from app.services.target_resolver import TargetResolverService


class TargetResolverServiceTest(unittest.TestCase):
    def test_resolver_returns_only_long_directional_targets(self) -> None:
        features = _features().model_copy(
            update={
                "previous_day_high": 99.0,
                "session_high": 103.0,
                "session_low": 96.0,
                "donchian_high_20": 104.0,
                "donchian_low_20": 94.0,
            }
        )

        targets = TargetResolverService().resolve(
            direction="LONG",
            entry=100.0,
            stop_loss=98.0,
            features=features,
        )

        self.assertTrue(targets)
        self.assertTrue(all(target.price is not None and target.price > 100.0 for target in targets))
        self.assertNotIn("previous_day_high", {target.source for target in targets})

    def test_resolver_returns_only_short_directional_targets(self) -> None:
        features = _features().model_copy(
            update={
                "previous_day_low": 101.0,
                "session_low": 97.0,
                "session_high": 104.0,
                "donchian_high_20": 106.0,
                "donchian_low_20": 96.0,
            }
        )

        targets = TargetResolverService().resolve(
            direction="SHORT",
            entry=100.0,
            stop_loss=102.0,
            features=features,
        )

        self.assertTrue(targets)
        self.assertTrue(all(target.price is not None and target.price < 100.0 for target in targets))
        self.assertNotIn("previous_day_low", {target.source for target in targets})

    def test_nearest_liquidity_pool_target_source_is_attached(self) -> None:
        alpha_context = AlphaMarketContext(
            symbol="BTCUSDT",
            timeframe="15m",
            timestamp=1,
            session_liquidity_pools=[
                LiquidityPoolFeatures(
                    name="equal highs",
                    price=102.0,
                    side="above",
                    source="session_equal_highs",
                    strength=88.0,
                )
            ],
        )

        targets = TargetResolverService().resolve(
            direction="LONG",
            entry=100.0,
            stop_loss=98.0,
            features=_features(),
            alpha_context=alpha_context,
        )

        self.assertEqual(targets[0].source, "nearest_liquidity_pool")
        self.assertEqual(targets[0].metadata["pool_name"], "equal highs")
        self.assertAlmostEqual(targets[0].metadata["r_multiple"], 1.0)

    def test_r_multiple_fallback_requires_explicit_research_flag(self) -> None:
        features = _features()
        service = TargetResolverService()

        no_fallback = service.resolve(
            direction="LONG",
            entry=100.0,
            stop_loss=98.0,
            features=features,
        )
        fallback = service.resolve(
            direction="LONG",
            entry=100.0,
            stop_loss=98.0,
            features=features,
            allow_r_multiple_fallback=True,
        )

        self.assertEqual(no_fallback, [])
        self.assertEqual([target.source for target in fallback], ["risk_multiple_fallback", "risk_multiple_fallback"])
        self.assertTrue(all(target.metadata.get("fallback_target_used") for target in fallback))


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1,
        price=100.0,
        open=99.5,
        high=100.5,
        low=99.0,
        close=100.0,
        price_change_1m=0.0,
        volume=100.0,
        volume_spike=1.0,
        volume_ma_20=100.0,
        volatility=1.0,
        history_length=200,
        atr_14=2.0,
    )


if __name__ == "__main__":
    unittest.main()
