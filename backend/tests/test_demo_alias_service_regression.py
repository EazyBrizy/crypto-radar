from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import AppUser
from app.services.exchange_connection_service import ExchangeConnectionService
from app.services.risk_state import RiskStateService
from app.services.strategy_config_service import StrategyConfigService

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")


class DemoAliasServiceRegressionTest(unittest.TestCase):
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
        _seed_demo_user(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_risk_state_accepts_usr_demo_when_demo_seed_exists(self) -> None:
        service = RiskStateService(self.SessionFactory)

        state = service.get_state(user_id="usr_demo")

        self.assertEqual(state.user_id, "demo")
        self.assertEqual(state.protection_state, "normal")

    def test_strategy_configs_accept_usr_demo_when_demo_seed_exists(self) -> None:
        service = StrategyConfigService(self.SessionFactory)

        configs = service.list_configs(user_id="usr_demo")

        self.assertEqual(configs, [])

    def test_exchange_connection_list_accepts_usr_demo_when_demo_seed_exists(self) -> None:
        service = ExchangeConnectionService(self.SessionFactory)

        connections = service.list_connections(user_id="usr_demo")

        self.assertEqual(connections, [])


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        for statement in _SQLITE_DDL:
            connection.execute(text(statement))


def _seed_demo_user(session_factory: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=USER_ID,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


_SQLITE_DDL = [
    """
    CREATE TABLE app_users (
        id UUID PRIMARY KEY,
        email TEXT NOT NULL,
        username TEXT,
        status TEXT,
        locale TEXT,
        timezone TEXT,
        risk_profile TEXT,
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE user_profiles (
        user_id UUID PRIMARY KEY,
        display_name TEXT,
        avatar_url TEXT,
        onboarding_done BOOLEAN,
        settings JSON,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE user_auth_identities (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL,
        provider TEXT NOT NULL,
        provider_subject TEXT NOT NULL,
        email TEXT,
        created_at DATETIME,
        updated_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES app_users(id),
        UNIQUE(provider, provider_subject)
    )
    """,
    """
    CREATE TABLE portfolios (
        id UUID PRIMARY KEY,
        user_id UUID,
        type TEXT,
        name TEXT,
        base_currency TEXT,
        status TEXT,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE portfolio_balances (
        portfolio_id UUID,
        asset_id UUID,
        available NUMERIC,
        locked NUMERIC,
        updated_at DATETIME,
        PRIMARY KEY (portfolio_id, asset_id)
    )
    """,
    """
    CREATE TABLE risk_protection_state (
        user_id UUID PRIMARY KEY,
        state TEXT,
        loss_streak INTEGER,
        daily_loss_amount NUMERIC,
        weekly_loss_amount NUMERIC,
        daily_window_start DATETIME,
        weekly_window_start DATETIME,
        window_timezone TEXT,
        peak_equity NUMERIC,
        current_equity NUMERIC,
        adaptive_multiplier NUMERIC,
        reason TEXT,
        metadata JSON DEFAULT '{}',
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE market_exchanges (
        id UUID PRIMARY KEY,
        code TEXT,
        name TEXT,
        type TEXT,
        status TEXT,
        api_base_url TEXT,
        ws_base_url TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE market_assets (
        id UUID PRIMARY KEY,
        symbol TEXT,
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
        exchange_id UUID,
        base_asset_id UUID,
        quote_asset_id UUID,
        symbol TEXT,
        status TEXT,
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
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE asset_risk_groups (
        id UUID PRIMARY KEY,
        asset_id UUID,
        group_code TEXT,
        group_name TEXT,
        is_primary BOOLEAN,
        source TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE exchange_instrument_rules (
        id UUID PRIMARY KEY,
        exchange_id UUID,
        pair_id UUID,
        symbol TEXT,
        category TEXT,
        min_order_size NUMERIC,
        max_order_size NUMERIC,
        min_notional NUMERIC,
        qty_step NUMERIC,
        tick_size NUMERIC,
        max_leverage INTEGER,
        funding_interval_minutes INTEGER,
        raw_payload JSON,
        source TEXT,
        fetched_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE positions (
        id UUID PRIMARY KEY,
        user_id UUID,
        portfolio_id UUID,
        signal_id UUID,
        pair_id UUID,
        mode TEXT,
        side TEXT,
        status TEXT,
        quantity NUMERIC,
        entry_avg_price NUMERIC,
        exit_avg_price NUMERIC,
        stop_loss NUMERIC,
        take_profit JSON,
        opened_at DATETIME,
        closed_at DATETIME,
        realized_pnl NUMERIC,
        fees_total NUMERIC,
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE position_risk_snapshots (
        position_id UUID PRIMARY KEY,
        risk_decision_id UUID,
        risk_amount NUMERIC,
        risk_percent NUMERIC,
        adjusted_risk_amount NUMERIC,
        rr NUMERIC,
        leverage INTEGER,
        margin_mode TEXT,
        liquidation_price NUMERIC,
        liquidation_buffer_percent NUMERIC,
        correlation_group TEXT,
        strategy_multiplier NUMERIC,
        signal_multiplier NUMERIC,
        fee_estimate NUMERIC,
        slippage_estimate NUMERIC,
        funding_buffer NUMERIC,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE user_exchange_connections (
        id UUID PRIMARY KEY,
        user_id UUID,
        exchange_id UUID,
        label TEXT,
        account_type TEXT,
        key_ref TEXT,
        permissions JSON,
        status TEXT,
        environment TEXT DEFAULT 'testnet',
        order_placement_mode TEXT DEFAULT 'dry_run',
        mainnet_explicitly_enabled BOOLEAN DEFAULT 0,
        last_sync_at DATETIME,
        last_account_snapshot_at DATETIME,
        account_snapshot_status TEXT DEFAULT 'missing',
        revoked_at DATETIME,
        deleted_at DATETIME,
        deletion_reason TEXT,
        metadata JSON,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE strategy_templates (
        id UUID PRIMARY KEY,
        code TEXT,
        name TEXT,
        category TEXT,
        description TEXT,
        risk_level TEXT,
        is_active BOOLEAN,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE strategy_versions (
        id UUID PRIMARY KEY,
        strategy_id UUID,
        version TEXT,
        config_schema JSON,
        default_params JSON,
        changelog TEXT,
        status TEXT,
        created_at DATETIME
    )
    """,
    """
    CREATE TABLE user_strategy_configs (
        id UUID PRIMARY KEY,
        user_id UUID,
        strategy_version_id UUID,
        name TEXT,
        exchange_scope JSON,
        pair_scope JSON,
        timeframes JSON,
        params JSON,
        risk_settings JSON,
        is_enabled BOOLEAN,
        created_at DATETIME,
        updated_at DATETIME
    )
    """,
]


if __name__ == "__main__":
    unittest.main()
