import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models.market import MarketAsset, MarketExchange, MarketPair
from app.models.outbox import OutboxEvent
from app.models.signal import TradingSignal, TradingSignalEvent
from app.models.strategy import StrategyTemplate, StrategyVersion
from app.repositories.signal_repository import (
    SIGNAL_EXPIRED_EVENT,
    PostgresSignalRepository,
)
from app.schemas.signal import StrategySignal
from app.workers.signal_worker import SignalExpiryWorker


class SignalRepositoryExpiryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._original_ttl = settings.signal_active_ttl_seconds
        settings.signal_active_ttl_seconds = 3600
        self._type_patches = _patch_sqlite_column_types()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )

        class TestSession(Session):
            pass

        self._session_class = TestSession
        self.commit_count = 0
        self.flush_count = 0

        def after_commit(_session: Session) -> None:
            self.commit_count += 1

        def after_flush(_session: Session, _flush_context: object) -> None:
            self.flush_count += 1

        self._after_commit_listener = after_commit
        self._after_flush_listener = after_flush
        event.listen(TestSession, "before_flush", _assign_sqlite_ids)
        event.listen(TestSession, "after_commit", self._after_commit_listener)
        event.listen(TestSession, "after_flush", self._after_flush_listener)
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
            class_=TestSession,
        )
        _create_sqlite_tables(self.engine)
        self._seed_references()
        self.repository = PostgresSignalRepository(
            session_factory=self.SessionFactory,
            signal_outcomes=_NoopSignalOutcomes(),
        )
        self.commit_count = 0
        self.flush_count = 0

    def tearDown(self) -> None:
        settings.signal_active_ttl_seconds = self._original_ttl
        event.remove(self._session_class, "before_flush", _assign_sqlite_ids)
        event.remove(self._session_class, "after_commit", self._after_commit_listener)
        event.remove(self._session_class, "after_flush", self._after_flush_listener)
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_list_open_signals_does_not_commit_or_write_expired_records(self) -> None:
        now = datetime.now(timezone.utc)
        stale_id = self._insert_signal(
            status="actionable",
            detected_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        fresh_id = self._insert_signal(
            status="actionable",
            detected_at=now,
            expires_at=now + timedelta(hours=1),
            direction="short",
        )
        self.commit_count = 0
        self.flush_count = 0

        signals = self.repository.list_open_signals()

        self.assertEqual([signal.id for signal in signals], [str(fresh_id)])
        self.assertEqual(self.commit_count, 0)
        self.assertEqual(self.flush_count, 0)
        with self.SessionFactory() as session:
            stale = session.scalars(
                select(TradingSignal).where(TradingSignal.id == stale_id)
            ).one()
            events = session.scalars(select(TradingSignalEvent)).all()
            outbox = session.scalars(select(OutboxEvent)).all()

        self.assertEqual(stale.status, "actionable")
        self.assertEqual(events, [])
        self.assertEqual(outbox, [])

    def test_expire_open_signals_transitions_expired_records_and_writes_event(self) -> None:
        now = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
        stale_id = self._insert_signal(
            status="actionable",
            detected_at=now - timedelta(hours=2),
            expires_at=now - timedelta(minutes=1),
        )
        self._insert_signal(
            status="actionable",
            detected_at=now,
            expires_at=now + timedelta(hours=1),
            direction="short",
        )

        expired_count = self.repository.expire_open_signals(now=now, limit=10)

        self.assertEqual(expired_count, 1)
        with self.SessionFactory() as session:
            stale = session.scalars(
                select(TradingSignal).where(TradingSignal.id == stale_id)
            ).one()
            events = session.scalars(
                select(TradingSignalEvent).where(TradingSignalEvent.signal_id == stale_id)
            ).all()
            outbox = session.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == stale_id)
            ).all()

        self.assertEqual(stale.status, "expired")
        self.assertIn("lifecycle_trace", stale.features_snapshot)
        self.assertEqual([event.event_type for event in events], [SIGNAL_EXPIRED_EVENT])
        self.assertEqual(events[0].old_status, "actionable")
        self.assertEqual(events[0].new_status, "expired")
        self.assertEqual([event.event_type for event in outbox], [SIGNAL_EXPIRED_EVENT])

    def test_upsert_existing_open_signal_extends_expiry_from_new_detected_at(self) -> None:
        created_at = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
        detected_at = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
        signal_id = self._insert_signal(
            status="actionable",
            detected_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            created_at=created_at,
        )

        result = self.repository.upsert_strategy_signal(_strategy_signal(detected_at))

        self.assertFalse(result.created)
        self.assertEqual(result.signal.id, str(signal_id))
        self.assertEqual(result.signal.expires_at, detected_at + timedelta(hours=1))
        with self.SessionFactory() as session:
            records = session.scalars(select(TradingSignal)).all()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].expires_at.replace(tzinfo=timezone.utc), detected_at + timedelta(hours=1))

    def test_fresh_updated_signal_stays_visible_despite_old_created_at(self) -> None:
        created_at = datetime(2026, 6, 5, 8, 0, tzinfo=timezone.utc)
        detected_at = datetime.now(timezone.utc).replace(microsecond=0)
        signal_id = self._insert_signal(
            status="actionable",
            detected_at=created_at,
            expires_at=created_at + timedelta(hours=1),
            created_at=created_at,
        )

        self.repository.upsert_strategy_signal(_strategy_signal(detected_at))

        visible = self.repository.list_open_signals()
        self.assertEqual([signal.id for signal in visible], [str(signal_id)])

    def test_incoming_signal_expired_by_timestamp_is_saved_expired(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stale_detected_at = now - timedelta(hours=2)

        result = self.repository.upsert_strategy_signal(_strategy_signal(stale_detected_at))

        self.assertEqual(result.signal.status, "expired")
        self.assertEqual(result.signal.expires_at, stale_detected_at + timedelta(hours=1))
        self.assertEqual(self.repository.list_open_signals(), [])

    def test_ttl_disabled_keeps_old_signal_open_without_expires_at(self) -> None:
        settings.signal_active_ttl_seconds = 0
        detected_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=3)

        result = self.repository.upsert_strategy_signal(_strategy_signal(detected_at))
        expired_count = self.repository.expire_open_signals(now=datetime.now(timezone.utc), limit=10)
        visible = self.repository.list_open_signals()

        self.assertEqual(result.signal.status, "actionable")
        self.assertIsNone(result.signal.expires_at)
        self.assertEqual(expired_count, 0)
        self.assertEqual([signal.id for signal in visible], [result.signal.id])

    def _seed_references(self) -> None:
        now = datetime.now(timezone.utc)
        self.exchange_id = uuid4()
        self.base_asset_id = uuid4()
        self.quote_asset_id = uuid4()
        self.pair_id = uuid4()
        self.strategy_id = uuid4()
        self.strategy_version_id = uuid4()
        with self.SessionFactory() as session:
            session.add_all(
                [
                    MarketExchange(
                        id=self.exchange_id,
                        code="bybit",
                        name="Bybit",
                        type="cex",
                        status="active",
                        metadata_={},
                        created_at=now,
                    ),
                    MarketAsset(
                        id=self.base_asset_id,
                        symbol="BTC",
                        name="Bitcoin",
                        asset_type="crypto",
                        metadata_={},
                        created_at=now,
                    ),
                    MarketAsset(
                        id=self.quote_asset_id,
                        symbol="USDT",
                        name="Tether",
                        asset_type="crypto",
                        metadata_={},
                        created_at=now,
                    ),
                    MarketPair(
                        id=self.pair_id,
                        exchange_id=self.exchange_id,
                        base_asset_id=self.base_asset_id,
                        quote_asset_id=self.quote_asset_id,
                        symbol="BTCUSDT",
                        status="active",
                        metadata_={},
                        created_at=now,
                    ),
                    StrategyTemplate(
                        id=self.strategy_id,
                        code="test_strategy",
                        name="Test Strategy",
                        category="test",
                        risk_level="medium",
                        is_active=True,
                        created_at=now,
                    ),
                    StrategyVersion(
                        id=self.strategy_version_id,
                        strategy_id=self.strategy_id,
                        version="1",
                        config_schema={},
                        default_params={},
                        status="active",
                        created_at=now,
                    ),
                ]
            )
            session.commit()

    def _insert_signal(
        self,
        *,
        status: str,
        detected_at: datetime,
        expires_at: datetime | None,
        direction: str = "long",
        created_at: datetime | None = None,
    ):
        signal_id = uuid4()
        created = created_at or detected_at
        with self.SessionFactory() as session:
            session.add(
                TradingSignal(
                    id=signal_id,
                    signal_key=f"signal-{signal_id}",
                    strategy_version_id=self.strategy_version_id,
                    exchange_id=self.exchange_id,
                    pair_id=self.pair_id,
                    timeframe="15m",
                    direction=direction,
                    status=status,
                    confidence=Decimal("0.80"),
                    score=Decimal("80"),
                    entry_price=Decimal("100"),
                    stop_loss=Decimal("95"),
                    take_profit=[105.0],
                    risk_reward=Decimal("2"),
                    detected_at=detected_at,
                    expires_at=expires_at,
                    features_snapshot={},
                    explanation="test",
                    created_at=created,
                    updated_at=created,
                )
            )
            session.commit()
        return signal_id


class SignalExpiryWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_expire_once_calls_service_explicitly(self) -> None:
        service = _FakeSignalExpiryService()
        worker = SignalExpiryWorker(store=service, interval_seconds=1, limit=25)

        result = await worker.expire_once()

        self.assertEqual(result, {"expired": 3, "limit": 25})
        self.assertEqual(service.calls, [{"now": None, "limit": 25}])


class _NoopSignalOutcomes:
    def create_tracking_for_signal(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _FakeSignalExpiryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def expire_open_signals(self, now: datetime | None = None, limit: int = 500) -> int:
        self.calls.append({"now": now, "limit": limit})
        return 3


def _strategy_signal(detected_at: datetime) -> StrategySignal:
    return StrategySignal(
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="test_strategy",
        direction="LONG",
        confidence=0.8,
        score=80,
        timestamp=int(detected_at.timestamp()),
        timeframe="15m",
        status="actionable",
        entry_min=99.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=105.0,
        risk_reward=2.0,
    )


def _assign_sqlite_ids(session: Session, _flush_context: object, _instances: object) -> None:
    for record in session.new:
        if isinstance(record, (TradingSignal, TradingSignalEvent, OutboxEvent)) and record.id is None:
            record.id = uuid4()


def _patch_sqlite_column_types() -> list[tuple[Any, Any]]:
    patches: list[tuple[Any, Any]] = []
    for table in (
        MarketExchange.__table__,
        MarketAsset.__table__,
        MarketPair.__table__,
        StrategyVersion.__table__,
        TradingSignal.__table__,
        TradingSignalEvent.__table__,
        OutboxEvent.__table__,
    ):
        for column in table.c:
            if column.type.__class__.__name__ == "JSONB":
                patches.append((column, column.type))
                column.type = JSON()
    return patches


def _restore_column_types(patches: list[tuple[Any, Any]]) -> None:
    for column, original_type in patches:
        column.type = original_type


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


_SQLITE_DDL = [
    """
    CREATE TABLE market_exchanges (
        id UUID PRIMARY KEY,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        status TEXT NOT NULL,
        api_base_url TEXT,
        ws_base_url TEXT,
        metadata JSON NOT NULL,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE market_assets (
        id UUID PRIMARY KEY,
        symbol TEXT NOT NULL,
        name TEXT,
        asset_type TEXT NOT NULL,
        decimals INTEGER,
        coingecko_id TEXT,
        metadata JSON NOT NULL,
        created_at DATETIME NOT NULL
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
        metadata JSON NOT NULL,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE strategy_templates (
        id UUID PRIMARY KEY,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        risk_level TEXT NOT NULL,
        is_active BOOLEAN NOT NULL,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE strategy_versions (
        id UUID PRIMARY KEY,
        strategy_id UUID NOT NULL,
        version TEXT NOT NULL,
        config_schema JSON NOT NULL,
        default_params JSON NOT NULL,
        changelog TEXT,
        status TEXT NOT NULL,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE trading_signals (
        id UUID PRIMARY KEY,
        signal_key TEXT NOT NULL,
        strategy_version_id UUID NOT NULL,
        exchange_id UUID NOT NULL,
        pair_id UUID NOT NULL,
        timeframe TEXT NOT NULL,
        direction TEXT NOT NULL,
        status TEXT NOT NULL,
        confidence NUMERIC NOT NULL,
        score NUMERIC NOT NULL,
        entry_price NUMERIC,
        stop_loss NUMERIC,
        take_profit JSON NOT NULL,
        risk_reward NUMERIC,
        detected_at DATETIME NOT NULL,
        expires_at DATETIME,
        features_snapshot JSON NOT NULL,
        explanation TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE trading_signal_events (
        id UUID NOT NULL,
        signal_id UUID NOT NULL,
        event_type TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        payload JSON NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY (id, created_at)
    )
    """,
    """
    CREATE TABLE outbox_events (
        id UUID NOT NULL,
        aggregate_type TEXT NOT NULL,
        aggregate_id UUID NOT NULL,
        event_type TEXT NOT NULL,
        payload JSON NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        next_retry_at DATETIME,
        created_at DATETIME NOT NULL,
        published_at DATETIME,
        PRIMARY KEY (id, created_at)
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
