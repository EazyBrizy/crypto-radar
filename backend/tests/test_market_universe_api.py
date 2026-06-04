import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import market_universe as market_universe_api
from app.api.v1 import watchlists as watchlists_api
from app.core.database import get_db_session
from app.models.market import MarketAsset, MarketExchange, MarketPair
from app.services.market_universe_service import MarketUniverseSyncResult
from app.services.watchlist_service import WatchlistService

EXCHANGE_ID = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")


class MarketUniverseApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )
        _create_sqlite_tables(self.engine)
        _seed_exchange(self.SessionFactory)
        app = FastAPI()
        app.dependency_overrides[get_db_session] = self._session_override
        app.include_router(market_universe_api.router, prefix="/api/v1")
        app.include_router(watchlists_api.router, prefix="/api/v1")
        self.client = TestClient(app)
        self.watchlist_service_patcher = patch(
            "app.api.v1.watchlists.watchlist_service",
            WatchlistService(self.SessionFactory),
        )
        self.watchlist_service_patcher.start()

    def tearDown(self) -> None:
        self.watchlist_service_patcher.stop()
        self.engine.dispose()

    def test_get_market_universe_pairs_returns_persisted_pairs_sorted_by_rank(self) -> None:
        _seed_pair(
            self.SessionFactory,
            symbol="ETHUSDT",
            base_asset="ETH",
            liquidity_rank=2,
            turnover_24h=Decimal("200"),
        )
        _seed_pair(
            self.SessionFactory,
            symbol="BTCUSDT",
            base_asset="BTC",
            liquidity_rank=1,
            turnover_24h=Decimal("300"),
        )
        _seed_pair(
            self.SessionFactory,
            symbol="SOLUSDT",
            base_asset="SOL",
            liquidity_rank=3,
            turnover_24h=Decimal("100"),
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe") as fetcher:
            response = self.client.get("/api/v1/market-universe/pairs")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["symbol"] for item in payload], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(payload[0]["exchange"], "bybit")
        self.assertEqual(payload[0]["base_asset"], "BTC")
        self.assertEqual(payload[0]["quote_asset"], "USDT")
        self.assertEqual(Decimal(str(payload[0]["turnover_24h"])), Decimal("300"))
        fetcher.assert_not_called()

    def test_post_sync_calls_service_and_returns_counts(self) -> None:
        calls: list[dict[str, object]] = []
        synced_at = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

        def fake_sync(_session: Any, **kwargs: object) -> MarketUniverseSyncResult:
            calls.append(kwargs)
            return MarketUniverseSyncResult(
                exchange="bybit",
                category="linear",
                quote="USDT",
                requested_limit="top_100",
                synced_count=100,
                total_available_count=245,
                skipped_count=145,
                synced_at=synced_at,
                warnings=["partial universe"],
            )

        with patch("app.api.v1.market_universe.sync_exchange_universe", fake_sync):
            response = self.client.post(
                "/api/v1/market-universe/sync",
                json={"exchange": "bybit", "category": "linear", "quote": "USDT", "limit": "top_100"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                {
                    "exchange": "bybit",
                    "category": "linear",
                    "quote": "USDT",
                    "limit": "top_100",
                    "sort": "turnover_24h_desc",
                    "persist": True,
                }
            ],
        )
        payload = response.json()
        self.assertEqual(payload["synced_count"], 100)
        self.assertEqual(payload["total_available_count"], 245)
        self.assertEqual(payload["skipped_count"], 145)
        self.assertEqual(payload["warnings"], ["partial universe"])

    def test_search_filters_symbol(self) -> None:
        _seed_pair(self.SessionFactory, symbol="BTCUSDT", base_asset="BTC", liquidity_rank=1)
        _seed_pair(self.SessionFactory, symbol="ETHUSDT", base_asset="ETH", liquidity_rank=2)

        response = self.client.get("/api/v1/market-universe/pairs", params={"search": "btc"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["symbol"] for item in response.json()], ["BTCUSDT"])

    def test_market_universe_limit_values_are_parsed(self) -> None:
        for index in range(250):
            _seed_pair(
                self.SessionFactory,
                symbol=f"COIN{index:03d}USDT",
                base_asset=f"COIN{index:03d}",
                liquidity_rank=index + 1,
                turnover_24h=Decimal(250 - index),
            )

        counts: dict[str, int] = {}
        for limit in ("top_100", "top_200", "top_500", "all"):
            response = self.client.get("/api/v1/market-universe/pairs", params={"limit": limit})
            self.assertEqual(response.status_code, 200)
            counts[limit] = len(response.json())

        self.assertEqual(counts, {"top_100": 100, "top_200": 200, "top_500": 250, "all": 250})

    def test_legacy_market_pairs_endpoint_keeps_compact_response_shape(self) -> None:
        _seed_pair(
            self.SessionFactory,
            symbol="LEGACYUSDT",
            base_asset="LEGACY",
            category=None,
            liquidity_rank=1,
        )

        response = self.client.get("/api/v1/market-pairs")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(
            set(payload[0]),
            {"id", "exchange", "symbol", "base_asset", "quote_asset", "status"},
        )
        self.assertEqual(payload[0]["symbol"], "LEGACYUSDT")

    def _session_override(self):
        with self.SessionFactory() as session:
            yield session


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


def _seed_exchange(session_factory: Any) -> None:
    with session_factory() as session:
        session.add(
            MarketExchange(
                id=EXCHANGE_ID,
                code="bybit",
                name="Bybit",
                type="cex",
                status="active",
                api_base_url="https://api.bybit.com",
                ws_base_url=None,
                metadata_={},
            )
        )
        session.commit()


def _seed_pair(
    session_factory: Any,
    *,
    symbol: str,
    base_asset: str,
    category: str | None = "linear",
    liquidity_rank: int,
    turnover_24h: Decimal = Decimal("100"),
) -> None:
    now = datetime.now(timezone.utc)
    quote_asset = "USDT"
    with session_factory() as session:
        base = MarketAsset(
            id=uuid4(),
            symbol=base_asset,
            name=None,
            asset_type="crypto",
            metadata_={},
        )
        quote = session.query(MarketAsset).filter(MarketAsset.symbol == quote_asset).one_or_none()
        if quote is None:
            quote = MarketAsset(
                id=uuid4(),
                symbol=quote_asset,
                name=None,
                asset_type="crypto",
                metadata_={},
            )
            session.add(quote)
            session.flush()
        session.add(base)
        session.flush()
        session.add(
            MarketPair(
                id=uuid4(),
                exchange_id=EXCHANGE_ID,
                base_asset_id=base.id,
                quote_asset_id=quote.id,
                symbol=symbol,
                status="active",
                market_type="linear_perpetual",
                category=category,
                quote_volume_24h=turnover_24h,
                base_volume_24h=Decimal("10"),
                turnover_24h=turnover_24h,
                last_price=Decimal("100"),
                mark_price=Decimal("100"),
                bid_price=Decimal("99"),
                ask_price=Decimal("101"),
                spread_bps=Decimal("200"),
                funding_rate=Decimal("0.0001"),
                liquidity_rank=liquidity_rank,
                liquidity_tier="high",
                exchange_status="Trading",
                universe_source="test",
                synced_at=now,
                metadata_={},
            )
        )
        session.commit()


_SQLITE_DDL = [
    """
    CREATE TABLE market_exchanges (
        id UUID PRIMARY KEY,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        status TEXT NOT NULL,
        api_base_url TEXT,
        ws_base_url TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE market_assets (
        id UUID PRIMARY KEY,
        symbol TEXT NOT NULL UNIQUE,
        name TEXT,
        asset_type TEXT,
        decimals INTEGER,
        coingecko_id TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE market_pairs (
        id UUID PRIMARY KEY,
        exchange_id UUID NOT NULL,
        base_asset_id UUID NOT NULL,
        quote_asset_id UUID NOT NULL,
        symbol TEXT NOT NULL,
        status TEXT NOT NULL,
        min_qty NUMERIC,
        tick_size NUMERIC,
        lot_size NUMERIC,
        market_type TEXT,
        category TEXT,
        quote_volume_24h NUMERIC,
        base_volume_24h NUMERIC,
        turnover_24h NUMERIC,
        last_price NUMERIC,
        mark_price NUMERIC,
        bid_price NUMERIC,
        ask_price NUMERIC,
        spread_bps NUMERIC,
        funding_rate NUMERIC,
        liquidity_rank INTEGER,
        liquidity_tier TEXT,
        exchange_status TEXT,
        universe_source TEXT,
        synced_at DATETIME,
        metadata JSON,
        created_at DATETIME,
        UNIQUE(exchange_id, symbol)
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
