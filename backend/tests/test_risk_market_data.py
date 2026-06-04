import time
import unittest

from app.schemas.market import OrderBookLevel, OrderBookSnapshot
from app.schemas.user import RiskManagementSettings
from app.services.market_persistence import orderbook_hot_key
from app.services.risk_management import (
    calculate_position_sizing,
    calculate_risk_check_result,
    calculate_trade_risk_adjustment,
)
from app.services.risk_market_data import RiskMarketDataService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str):
        return self.values.get(name)


class RiskMarketDataOrderbookTest(unittest.TestCase):
    def test_risk_market_data_uses_fresh_orderbook_snapshot(self) -> None:
        redis = FakeRedis()
        redis.values[orderbook_hot_key(exchange="bybit", symbol="BTCUSDT")] = _snapshot_json(
            timestamp=int(time.time() * 1000),
            bid_depth_usd_0_5_pct=300.0,
            ask_depth_usd_0_5_pct=400.4,
        )
        service = RiskMarketDataService(
            ticker_fetcher=lambda **_kwargs: [],
            redis_client_factory=lambda: redis,
            orderbook_max_age_seconds=30,
            position_provider=None,
        )

        snapshot = service.build_snapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="long",
            mode="virtual",
            instrument_type="futures",
            fallback_entry_price=99,
        )

        self.assertEqual(snapshot.market_data_status, "fresh")
        self.assertEqual(snapshot.market_data_source, "bybit_v5_orderbook")
        self.assertEqual(snapshot.best_bid, 100.0)
        self.assertEqual(snapshot.best_ask, 100.1)
        self.assertEqual(snapshot.entry_price, 100.1)
        self.assertEqual(snapshot.orderbook_depth_usd, 400.4)
        self.assertIsNotNone(snapshot.orderbook_snapshot)
        self.assertEqual(snapshot.orderbook_snapshot.freshness_status, "fresh")
        self.assertEqual(snapshot.orderbook_snapshot.best_bid, 100.0)
        self.assertEqual(snapshot.orderbook_snapshot.best_ask, 100.1)
        self.assertEqual(snapshot.orderbook_snapshot.depth_levels, 2)
        self.assertAlmostEqual(snapshot.spread_bps or 0, 9.995)

    def test_stale_orderbook_snapshot_is_explicit(self) -> None:
        redis = FakeRedis()
        redis.values[orderbook_hot_key(exchange="bybit", symbol="BTCUSDT")] = _snapshot_json(
            timestamp=int(time.time() * 1000) - 120_000,
            bid_depth_usd_0_5_pct=300.0,
            ask_depth_usd_0_5_pct=400.4,
        )
        service = RiskMarketDataService(
            ticker_fetcher=lambda **_kwargs: [],
            redis_client_factory=lambda: redis,
            orderbook_max_age_seconds=5,
            position_provider=None,
        )

        snapshot = service.build_snapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="short",
            mode="virtual",
            instrument_type="futures",
            fallback_entry_price=99,
        )

        self.assertEqual(snapshot.market_data_status, "stale")
        self.assertEqual(snapshot.entry_price, 100.0)
        self.assertEqual(snapshot.orderbook_depth_usd, 300.0)
        self.assertIn("Bybit L2 orderbook snapshot is stale.", snapshot.warnings)

    def test_placeholder_orderbook_is_missing_not_fresh(self) -> None:
        redis = FakeRedis()
        redis.values[orderbook_hot_key(exchange="bybit", symbol="BTCUSDT")] = (
            '{"bids":[],"asks":[],"ts":"2026-05-25T12:00:00Z","source":"orderbook_l2_not_available"}'
        )
        service = RiskMarketDataService(
            ticker_fetcher=lambda **_kwargs: [],
            redis_client_factory=lambda: redis,
            orderbook_max_age_seconds=30,
            position_provider=None,
        )

        snapshot = service.build_snapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            side="long",
            mode="virtual",
            instrument_type="futures",
            fallback_entry_price=99,
        )

        self.assertEqual(snapshot.market_data_status, "missing")
        self.assertIsNone(snapshot.orderbook_depth_usd)
        self.assertIn("Bybit L2 orderbook snapshot is missing.", snapshot.warnings)

    def test_real_risk_blocks_stale_orderbook_when_fresh_data_required(self) -> None:
        result = _risk_check(
            execution_mode="real",
            market_data_status="stale",
            orderbook_depth_usd=None,
            real_requires_fresh_market_data=True,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Bybit market data is stale.", result.blockers)
        self.assertIn("Orderbook liquidity is unavailable.", result.blockers)

    def test_virtual_risk_warns_on_stale_orderbook(self) -> None:
        result = _risk_check(
            execution_mode="virtual",
            market_data_status="stale",
            orderbook_depth_usd=None,
            real_requires_fresh_market_data=True,
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("Bybit market data is stale.", result.warnings)
        self.assertIn("Orderbook liquidity is unavailable.", result.warnings)

    def test_real_risk_warns_when_fresh_market_data_not_required(self) -> None:
        result = _risk_check(
            execution_mode="real",
            market_data_status="stale",
            orderbook_depth_usd=None,
            real_requires_fresh_market_data=False,
        )

        self.assertEqual(result.status, "warning")
        self.assertEqual(result.blockers, [])
        self.assertIn("Bybit market data is stale.", result.warnings)
        self.assertIn("Orderbook liquidity is unavailable.", result.warnings)

    def test_fresh_orderbook_snapshot_vwap_passes(self) -> None:
        orderbook = _orderbook_snapshot(
            timestamp=int(time.time() * 1000),
            asks=[
                OrderBookLevel(price=100.1, quantity=30.0),
                OrderBookLevel(price=100.2, quantity=30.0),
            ],
            bid_depth_usd_0_5_pct=100_000.0,
            ask_depth_usd_0_5_pct=100_000.0,
            freshness_status="fresh",
        )
        result = _risk_check(
            execution_mode="virtual",
            market_data_status="fresh",
            orderbook_depth_usd=100_000.0,
            real_requires_fresh_market_data=True,
            orderbook_snapshot=orderbook,
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.orderbook_freshness_status, "fresh")
        self.assertEqual(result.orderbook_source, "bybit_v5_orderbook")
        self.assertEqual(result.orderbook_depth_levels, 3)
        self.assertIsNotNone(result.orderbook_vwap_price)
        self.assertIsNotNone(result.orderbook_vwap_impact_bps)
        self.assertIsNotNone(result.orderbook_slippage_bps)

    def test_missing_depth_warns_virtual(self) -> None:
        result = _risk_check(
            execution_mode="virtual",
            market_data_status="fresh",
            orderbook_depth_usd=None,
            real_requires_fresh_market_data=True,
        )

        self.assertEqual(result.status, "warning")
        self.assertIn("Orderbook liquidity is unavailable.", result.warnings)
        self.assertEqual(result.blockers, [])

    def test_missing_depth_blocks_real_when_fresh_data_required(self) -> None:
        result = _risk_check(
            execution_mode="real",
            market_data_status="fresh",
            orderbook_depth_usd=None,
            real_requires_fresh_market_data=True,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("Orderbook liquidity is unavailable.", result.blockers)


def _snapshot_json(
    *,
    timestamp: int,
    bid_depth_usd_0_5_pct: float,
    ask_depth_usd_0_5_pct: float,
) -> str:
    snapshot = OrderBookSnapshot(
        exchange="bybit",
        symbol="BTCUSDT",
        category="linear",
        bids=[OrderBookLevel(price=100.0, quantity=1.0)],
        asks=[OrderBookLevel(price=100.1, quantity=2.0)],
        timestamp=timestamp,
        ts="2026-05-25T12:00:00Z",
        source="bybit_v5_orderbook",
        spread_bps=9.995,
        bid_depth_usd_0_1_pct=100.0,
        ask_depth_usd_0_1_pct=200.2,
        bid_depth_usd_0_5_pct=bid_depth_usd_0_5_pct,
        ask_depth_usd_0_5_pct=ask_depth_usd_0_5_pct,
        bid_depth_usd_1_pct=bid_depth_usd_0_5_pct,
        ask_depth_usd_1_pct=ask_depth_usd_0_5_pct,
    )
    return snapshot.model_dump_json(exclude_none=True)


def _orderbook_snapshot(
    *,
    timestamp: int,
    asks: list[OrderBookLevel],
    bid_depth_usd_0_5_pct: float,
    ask_depth_usd_0_5_pct: float,
    freshness_status: str,
) -> OrderBookSnapshot:
    bids = [OrderBookLevel(price=100.0, quantity=10.0)]
    return OrderBookSnapshot(
        exchange="bybit",
        symbol="BTCUSDT",
        category="linear",
        bids=bids,
        asks=asks,
        timestamp=timestamp,
        source="bybit_v5_orderbook",
        freshness_status=freshness_status,
        spread_bps=9.995,
        bid_depth_usd_0_1_pct=bid_depth_usd_0_5_pct,
        ask_depth_usd_0_1_pct=ask_depth_usd_0_5_pct,
        bid_depth_usd_0_5_pct=bid_depth_usd_0_5_pct,
        ask_depth_usd_0_5_pct=ask_depth_usd_0_5_pct,
        bid_depth_usd_1_pct=bid_depth_usd_0_5_pct,
        ask_depth_usd_1_pct=ask_depth_usd_0_5_pct,
    )


def _risk_check(
    *,
    execution_mode: str,
    market_data_status: str,
    orderbook_depth_usd: float | None,
    real_requires_fresh_market_data: bool,
    orderbook_snapshot: OrderBookSnapshot | None = None,
):
    settings = RiskManagementSettings(
        take_profit_required=False,
        real_requires_positive_edge=False,
        real_requires_fresh_market_data=real_requires_fresh_market_data,
    )
    risk_adjustment = calculate_trade_risk_adjustment(
        account_equity=10_000,
        risk_settings=settings,
        instrument_type="spot",
        strategy="trend_pullback_continuation",
        signal_score=90,
    )
    sizing = calculate_position_sizing(
        account_equity=10_000,
        risk_settings=settings,
        entry_price=100,
        stop_loss_price=95,
        side="long",
        risk_per_trade_percent=risk_adjustment.adjusted_risk_percent,
    )
    return calculate_risk_check_result(
        risk_settings=settings,
        risk_adjustment=risk_adjustment,
        position_sizing=sizing,
        execution_mode=execution_mode,
        market_data_status=market_data_status,
        best_bid=99.9,
        best_ask=100.1,
        orderbook_depth_usd=orderbook_depth_usd,
        orderbook_snapshot=orderbook_snapshot,
    )


if __name__ == "__main__":
    unittest.main()
