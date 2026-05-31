import json
import unittest
from decimal import Decimal

from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features, MarketData
from app.services.candle_service import CandleService
from app.services.derivative_market import DerivativeMarketSnapshot
from app.services.market_persistence import MarketDataPersistenceService
from app.services.market_scanner import MarketScanner


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, list[list[object]], list[str]]] = []

    def insert(
        self,
        table: str,
        data: list[list[object]],
        column_names: list[str],
    ) -> None:
        self.inserts.append((table, data, column_names))


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, tuple[int, str]] = {}

    def setex(self, name: str, time: int, value: str) -> None:
        self.values[name] = (time, value)


class FakeMarketPersistence:
    def __init__(self) -> None:
        self.ticks: list[MarketData] = []
        self.candle_batches: list[list[OHLCVCandle]] = []
        self.features: list[Features] = []

    def persist_tick(self, tick: MarketData) -> None:
        self.ticks.append(tick)

    def persist_candles(self, candles: list[OHLCVCandle]) -> int:
        self.candle_batches.append(candles)
        return len(candles)

    def persist_features(self, features: Features) -> None:
        self.features.append(features)


class FakeDerivativeMarket:
    def hot_snapshot(self, *, exchange: str, symbol: str) -> DerivativeMarketSnapshot:
        return DerivativeMarketSnapshot(
            exchange=exchange,
            symbol=symbol,
            funding_rate=0.001,
            source="test",
        )


class MarketDataPersistenceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clickhouse = FakeClickHouseClient()
        self.redis = FakeRedisClient()
        self.service = MarketDataPersistenceService(
            clickhouse_client_factory=lambda: self.clickhouse,
            redis_client_factory=lambda: self.redis,
        )

    def test_tick_writes_clickhouse_market_tables_and_redis_hot_keys(self) -> None:
        tick = MarketData(
            exchange="bybit",
            symbol="BTCUSDT",
            price=67_250.12,
            volume=0.42,
            timestamp=1_779_796_800_123,
        )

        self.service.persist_tick(tick)

        tables = [insert[0] for insert in self.clickhouse.inserts]
        self.assertEqual(tables, ["market.raw_exchange_events", "market.trades"])
        self.assertIn("price:bybit:BTCUSDT", self.redis.values)
        self.assertIn("orderbook:bybit:BTCUSDT", self.redis.values)

        price_ttl, price_payload_raw = self.redis.values["price:bybit:BTCUSDT"]
        self.assertEqual(price_ttl, 30)
        price_payload = json.loads(price_payload_raw)
        self.assertEqual(price_payload["price"], "67250.12")
        self.assertEqual(price_payload["bid"], "67250.12")
        self.assertEqual(price_payload["ask"], "67250.12")

        raw_payload = json.loads(self.clickhouse.inserts[0][1][0][-1])
        self.assertEqual(raw_payload["source"], "normalized_trade_tick")
        self.assertEqual(raw_payload["symbol"], "BTCUSDT")

    def test_candles_write_supported_ohlcv_tables(self) -> None:
        open_time = 1_779_796_800_000
        candles = [
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="1m",
                open_time=open_time,
                close_time=open_time + 59_999,
                open=67_000,
                high=67_300,
                low=66_900,
                close=67_250,
                volume=2,
                trades=4,
            ),
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="4h",
                open_time=open_time,
                close_time=open_time + 14_399_999,
                open=67_000,
                high=67_300,
                low=66_900,
                close=67_250,
                volume=2,
                trades=4,
            ),
        ]

        rows_written = self.service.persist_candles(candles)

        self.assertEqual(rows_written, 2)
        self.assertEqual(self.clickhouse.inserts[0][0], "market.ohlcv_1m")
        self.assertEqual(self.clickhouse.inserts[1][0], "market.ohlcv_4h")
        row = self.clickhouse.inserts[0][1][0]
        self.assertEqual(row[0:2], ["bybit", "BTCUSDT"])
        self.assertEqual(row[7], Decimal("2"))
        self.assertEqual(row[8], Decimal("134500"))

    def test_features_write_indicator_values(self) -> None:
        features = Features(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1m",
            timestamp=1_779_796_859_999,
            price=67_250,
            open=67_000,
            high=67_300,
            low=66_900,
            close=67_250,
            price_change_1m=0.01,
            volume=2,
            volume_spike=1.2,
            volume_ma_20=1.5,
            volatility=42,
            history_length=21,
            ema_20=67_100,
            ema_50=67_050,
            ema_200=None,
            rsi_14=55,
            atr_14=120,
        )

        self.service.persist_features(features)

        self.assertEqual(self.clickhouse.inserts[0][0], "market.indicator_values")
        row = self.clickhouse.inserts[0][1][0]
        self.assertEqual(row[0:3], ["bybit", "BTCUSDT", "1m"])
        self.assertEqual(row[4], 55)
        self.assertEqual(row[5], Decimal("67100"))
        self.assertEqual(row[9], Decimal("1.5"))
        self.assertIn('"history_length":21', row[10])


class MarketScannerPersistenceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_scanner_persists_tick_candle_and_features(self) -> None:
        persistence = FakeMarketPersistence()
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=persistence,
            market_quality=None,
            virtual_trading=None,
            derivative_market=FakeDerivativeMarket(),  # type: ignore[arg-type]
        )

        await scanner.process_tick(
            MarketData(
                exchange="bybit",
                symbol="BTCUSDT",
                price=67_250,
                volume=0.5,
                timestamp=1_779_796_800_123,
            )
        )

        self.assertEqual(len(persistence.ticks), 1)
        self.assertEqual(len(persistence.candle_batches), 1)
        self.assertEqual(len(persistence.candle_batches[0]), 1)
        self.assertEqual(len(persistence.features), 1)
        self.assertEqual(persistence.features[0].timeframe, "1m")
        self.assertEqual(persistence.features[0].funding_rate, 0.001)


if __name__ == "__main__":
    unittest.main()
