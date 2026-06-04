import unittest
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.exchanges.bybit import BybitInstrumentInfo, BybitTicker, BybitUniverseInstrument
from app.models.market import MarketAsset, MarketDerivativeSnapshot, MarketPair
from app.models.risk import ExchangeInstrumentRule
from app.services.market_universe_service import sync_exchange_universe


class MarketUniverseServiceTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_sync_top_100_persists_100_pairs_when_150_available(self) -> None:
        universe = tuple(
            _universe_item(index, turnover=Decimal(200_000_000 - index))
            for index in range(150)
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=universe):
            with self.SessionFactory() as session:
                result = sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="top_100",
                )

        with self.SessionFactory() as session:
            pair_count = session.scalar(select(func.count()).select_from(MarketPair))
            asset_count = session.scalar(select(func.count()).select_from(MarketAsset))
            top_pair = session.scalars(select(MarketPair).where(MarketPair.liquidity_rank == 1)).one()

        self.assertEqual(result.synced_count, 100)
        self.assertEqual(result.total_available_count, 150)
        self.assertEqual(result.skipped_count, 50)
        self.assertEqual(pair_count, 100)
        self.assertEqual(asset_count, 101)
        self.assertEqual(top_pair.symbol, "COIN000USDT")
        self.assertEqual(top_pair.liquidity_tier, "high")

    def test_sync_all_persists_all_trading_pairs(self) -> None:
        universe = (
            _universe_item(0, symbol="BTCUSDT", base_coin="BTC", turnover=Decimal("150000000")),
            _universe_item(1, symbol="ETHUSDT", base_coin="ETH", turnover=Decimal("50000000")),
            _universe_item(2, symbol="SOLUSDT", base_coin="SOL", turnover=Decimal("5000000")),
            _universe_item(3, symbol="DOGEUSDT", base_coin="DOGE", turnover=Decimal("1000000"), status="PreLaunch"),
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=universe):
            with self.SessionFactory() as session:
                result = sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )

        with self.SessionFactory() as session:
            pairs = session.scalars(select(MarketPair).order_by(MarketPair.liquidity_rank)).all()

        self.assertEqual(result.synced_count, 3)
        self.assertEqual(result.total_available_count, 3)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual([pair.symbol for pair in pairs], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])

    def test_second_sync_updates_pairs_without_duplicate_assets_or_pairs(self) -> None:
        first_universe = (
            _universe_item(0, symbol="BTCUSDT", base_coin="BTC", turnover=Decimal("100000000"), last_price=Decimal("100")),
            _universe_item(1, symbol="ETHUSDT", base_coin="ETH", turnover=Decimal("50000000"), last_price=Decimal("50")),
        )
        second_universe = (
            _universe_item(0, symbol="BTCUSDT", base_coin="BTC", turnover=Decimal("9000000"), last_price=Decimal("110")),
            _universe_item(1, symbol="ETHUSDT", base_coin="ETH", turnover=Decimal("250000000"), last_price=Decimal("60")),
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=first_universe):
            with self.SessionFactory() as session:
                sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )
        with self.SessionFactory() as session:
            initial_ids = {pair.symbol: pair.id for pair in session.scalars(select(MarketPair)).all()}

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=second_universe):
            with self.SessionFactory() as session:
                sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )

        with self.SessionFactory() as session:
            pairs = {pair.symbol: pair for pair in session.scalars(select(MarketPair)).all()}
            pair_count = session.scalar(select(func.count()).select_from(MarketPair))
            asset_count = session.scalar(select(func.count()).select_from(MarketAsset))

        self.assertEqual(pair_count, 2)
        self.assertEqual(asset_count, 3)
        self.assertEqual({symbol: pair.id for symbol, pair in pairs.items()}, initial_ids)
        self.assertEqual(pairs["BTCUSDT"].last_price, Decimal("110"))
        self.assertEqual(pairs["BTCUSDT"].turnover_24h, Decimal("9000000"))
        self.assertEqual(pairs["BTCUSDT"].liquidity_tier, "low")
        self.assertEqual(pairs["ETHUSDT"].liquidity_rank, 1)
        self.assertEqual(pairs["ETHUSDT"].liquidity_tier, "high")

    def test_liquidity_rank_and_tier_are_set(self) -> None:
        universe = (
            _universe_item(0, symbol="HIGHUSDT", base_coin="HIGH", turnover=Decimal("100000000")),
            _universe_item(1, symbol="MEDUSDT", base_coin="MED", turnover=Decimal("10000000")),
            _universe_item(2, symbol="LOWUSDT", base_coin="LOW", turnover=Decimal("9999999")),
            _universe_item(3, symbol="UNKNOWNUSDT", base_coin="UNKNOWN", turnover=None),
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=universe):
            with self.SessionFactory() as session:
                sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )

        with self.SessionFactory() as session:
            pairs = {pair.symbol: pair for pair in session.scalars(select(MarketPair)).all()}

        self.assertEqual(pairs["HIGHUSDT"].liquidity_rank, 1)
        self.assertEqual(pairs["HIGHUSDT"].liquidity_tier, "high")
        self.assertEqual(pairs["MEDUSDT"].liquidity_tier, "medium")
        self.assertEqual(pairs["LOWUSDT"].liquidity_tier, "low")
        self.assertEqual(pairs["UNKNOWNUSDT"].liquidity_tier, "unknown")

    def test_derivative_snapshots_and_instrument_rules_are_written(self) -> None:
        universe = (
            _universe_item(
                0,
                symbol="BTCUSDT",
                base_coin="BTC",
                turnover=Decimal("150000000"),
                mark_price=Decimal("50000.5"),
                funding_rate=Decimal("0.0002"),
                open_interest=Decimal("1234.5"),
            ),
        )

        with patch("app.services.market_universe_service.fetch_bybit_market_universe", return_value=universe):
            with self.SessionFactory() as session:
                sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )

        with self.SessionFactory() as session:
            snapshot = session.scalars(select(MarketDerivativeSnapshot)).one()
            rule = session.scalars(select(ExchangeInstrumentRule)).one()
            pair = session.scalars(select(MarketPair)).one()

        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.mark_price, Decimal("50000.5"))
        self.assertEqual(snapshot.funding_rate, Decimal("0.0002"))
        self.assertEqual(snapshot.open_interest, Decimal("1234.5"))
        self.assertEqual(snapshot.turnover_24h, Decimal("150000000"))
        self.assertEqual(rule.symbol, "BTCUSDT")
        self.assertEqual(rule.min_order_size, Decimal("0.001"))
        self.assertEqual(rule.qty_step, Decimal("0.001"))
        self.assertAlmostEqual(float(rule.tick_size or 0), 0.1)
        self.assertEqual(pair.min_qty, Decimal("0.001"))
        self.assertEqual(pair.lot_size, Decimal("0.001"))
        self.assertAlmostEqual(float(pair.tick_size or 0), 0.1)

    def test_unsupported_exchange_or_category_returns_clear_validation_error(self) -> None:
        with self.SessionFactory() as session:
            with self.assertRaisesRegex(ValueError, "supports only exchange='bybit'"):
                sync_exchange_universe(
                    session,
                    exchange="binance",
                    category="linear",
                    quote="USDT",
                    limit="all",
                )

        with self.SessionFactory() as session:
            with self.assertRaisesRegex(ValueError, "supports only category='linear'"):
                sync_exchange_universe(
                    session,
                    exchange="bybit",
                    category="spot",
                    quote="USDT",
                    limit="all",
                )


def _universe_item(
    index: int,
    *,
    symbol: str | None = None,
    base_coin: str | None = None,
    turnover: Decimal | None,
    status: str = "Trading",
    last_price: Decimal | None = None,
    mark_price: Decimal | None = None,
    funding_rate: Decimal = Decimal("0.0001"),
    open_interest: Decimal = Decimal("1000"),
) -> BybitUniverseInstrument:
    resolved_symbol = symbol or f"COIN{index:03d}USDT"
    resolved_base = base_coin or resolved_symbol.removesuffix("USDT")
    resolved_last = last_price or Decimal("100")
    resolved_mark = mark_price or resolved_last
    volume = None if turnover is None else Decimal("1000")
    bid = None if turnover is None else resolved_last - Decimal("1")
    ask = None if turnover is None else resolved_last + Decimal("1")
    ticker = None
    if turnover is not None:
        ticker = BybitTicker(
            category="linear",
            symbol=resolved_symbol,
            bid1_price=float(bid or 0),
            ask1_price=float(ask or 0),
            mark_price=float(resolved_mark),
            funding_rate=float(funding_rate),
            volume_24h=float(volume or 0),
            turnover_24h=float(turnover),
            raw_payload={
                "symbol": resolved_symbol,
                "bid1Price": str(bid),
                "ask1Price": str(ask),
                "markPrice": str(resolved_mark),
                "fundingRate": str(funding_rate),
                "volume24h": str(volume),
                "turnover24h": str(turnover),
                "openInterest": str(open_interest),
                "openInterestValue": str(open_interest * resolved_mark),
            },
            open_interest=float(open_interest),
            open_interest_value=float(open_interest * resolved_mark),
        )
    instrument = BybitInstrumentInfo(
        symbol=resolved_symbol,
        category="linear",
        status=status,
        base_coin=resolved_base,
        quote_coin="USDT",
        contract_type="LinearPerpetual",
        launch_time=1_670_601_600_000,
        delivery_time=0,
        price_filter={"tickSize": "0.1"},
        lot_size_filter={
            "minOrderQty": "0.001",
            "maxOrderQty": "100",
            "qtyStep": "0.001",
            "minNotionalValue": "5",
        },
        leverage_filter={"maxLeverage": "100"},
        raw_payload={
            "symbol": resolved_symbol,
            "status": status,
            "baseCoin": resolved_base,
            "quoteCoin": "USDT",
            "contractType": "LinearPerpetual",
            "priceFilter": {"tickSize": "0.1"},
            "lotSizeFilter": {
                "minOrderQty": "0.001",
                "maxOrderQty": "100",
                "qtyStep": "0.001",
                "minNotionalValue": "5",
            },
            "leverageFilter": {"maxLeverage": "100"},
            "fundingInterval": "480",
        },
    )
    return BybitUniverseInstrument(
        instrument=instrument,
        ticker=ticker,
        symbol=resolved_symbol,
        category="linear",
        status=status,
        base_coin=resolved_base,
        quote_coin="USDT",
        contract_type="LinearPerpetual",
        launch_time=1_670_601_600_000,
        delivery_time=0,
        turnover_24h=turnover,
        volume_24h=volume,
        last_price=None if turnover is None else resolved_last,
        mark_price=None if turnover is None else resolved_mark,
        bid1_price=bid,
        ask1_price=ask,
        spread_bps=None if bid is None or ask is None else (ask - bid) / resolved_last * Decimal("10000"),
        funding_rate=None if turnover is None else funding_rate,
        turnover_rank=index + 1 if turnover is not None else None,
    )


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


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
    """
    CREATE TABLE market_derivative_snapshots (
        id UUID PRIMARY KEY,
        exchange_id UUID NOT NULL,
        pair_id UUID,
        symbol TEXT NOT NULL,
        category TEXT NOT NULL,
        mark_price NUMERIC,
        funding_rate NUMERIC,
        open_interest NUMERIC,
        open_interest_value NUMERIC,
        oi_change NUMERIC,
        volume_24h NUMERIC,
        turnover_24h NUMERIC,
        source TEXT NOT NULL,
        raw_payload JSON,
        fetched_at DATETIME NOT NULL,
        updated_at DATETIME,
        created_at DATETIME,
        UNIQUE(exchange_id, symbol, category)
    )
    """,
    """
    CREATE TABLE exchange_instrument_rules (
        id UUID PRIMARY KEY,
        exchange_id UUID NOT NULL,
        pair_id UUID,
        symbol TEXT NOT NULL,
        category TEXT NOT NULL,
        min_order_size NUMERIC,
        max_order_size NUMERIC,
        min_notional NUMERIC,
        qty_step NUMERIC,
        tick_size NUMERIC,
        max_leverage INTEGER,
        funding_interval_minutes INTEGER,
        raw_payload JSON,
        source TEXT NOT NULL,
        fetched_at DATETIME,
        updated_at DATETIME,
        UNIQUE(exchange_id, category, symbol)
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
