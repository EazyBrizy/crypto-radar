from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models.market import MarketAsset, MarketExchange, MarketPair
from app.models.portfolio import Portfolio, PortfolioBalance, PortfolioBalanceLedger
from app.models.strategy import StrategyTemplate, StrategyVersion
from app.models.user import AppUser, SubscriptionPlan, UserProfile, UserSubscription
from app.models.watchlist import UserWatchlist, UserWatchlistPair

DEMO_USER_EMAIL = "demo@crypto-radar.local"
DEMO_USERNAME = "demo"
DEMO_PORTFOLIO_NAME = "Demo Virtual Portfolio"
DEFAULT_WATCHLIST_NAME = "Default"
BOOTSTRAP_EXTERNAL_PROVIDER = "bootstrap"
BOOTSTRAP_DEMO_SUBSCRIPTION_ID = "demo-user-pro"
BOOTSTRAP_STARTED_AT = datetime(2026, 5, 28, tzinfo=timezone.utc)
INITIAL_VIRTUAL_BALANCE = Decimal("100.000000000000000000")

SEED_EXCHANGES: list[dict[str, Any]] = [
    {
        "code": "bybit",
        "name": "Bybit",
        "type": "cex",
        "status": "active",
        "api_base_url": "https://api.bybit.com",
        "ws_base_url": "wss://stream.bybit.com/v5/public/linear",
        "metadata_": {"market_types": ["linear_perpetual", "spot"]},
    },
    {
        "code": "binance",
        "name": "Binance",
        "type": "cex",
        "status": "active",
        "api_base_url": "https://api.binance.com",
        "ws_base_url": "wss://stream.binance.com:9443/ws",
        "metadata_": {"market_types": ["spot", "usd_m_futures"]},
    },
    {
        "code": "okx",
        "name": "OKX",
        "type": "cex",
        "status": "active",
        "api_base_url": "https://www.okx.com",
        "ws_base_url": "wss://ws.okx.com:8443/ws/v5/public",
        "metadata_": {"market_types": ["spot", "swap"]},
    },
    {
        "code": "coinbase",
        "name": "Coinbase",
        "type": "cex",
        "status": "active",
        "api_base_url": "https://api.exchange.coinbase.com",
        "ws_base_url": "wss://ws-feed.exchange.coinbase.com",
        "metadata_": {"market_types": ["spot"]},
    },
]

SEED_ASSETS: list[dict[str, Any]] = [
    {"symbol": "USDT", "name": "Tether USDt", "asset_type": "crypto", "decimals": 6, "coingecko_id": "tether"},
    {"symbol": "USDC", "name": "USD Coin", "asset_type": "crypto", "decimals": 6, "coingecko_id": "usd-coin"},
    {"symbol": "BTC", "name": "Bitcoin", "asset_type": "crypto", "decimals": 8, "coingecko_id": "bitcoin"},
    {"symbol": "ETH", "name": "Ethereum", "asset_type": "crypto", "decimals": 18, "coingecko_id": "ethereum"},
    {"symbol": "SOL", "name": "Solana", "asset_type": "crypto", "decimals": 9, "coingecko_id": "solana"},
    {"symbol": "DOGE", "name": "Dogecoin", "asset_type": "crypto", "decimals": 8, "coingecko_id": "dogecoin"},
    {
        "symbol": "1000PEPE",
        "name": "1000 Pepe",
        "asset_type": "crypto",
        "decimals": 8,
        "coingecko_id": "pepe",
        "metadata_": {"underlying_symbol": "PEPE", "contract_multiplier": 1000},
    },
]

SEED_PAIRS: list[dict[str, Any]] = [
    {
        "exchange_code": "bybit",
        "base_symbol": "BTC",
        "quote_symbol": "USDT",
        "symbol": "BTCUSDT",
        "min_qty": Decimal("0.001"),
        "tick_size": Decimal("0.1"),
        "lot_size": Decimal("0.001"),
    },
    {
        "exchange_code": "bybit",
        "base_symbol": "ETH",
        "quote_symbol": "USDT",
        "symbol": "ETHUSDT",
        "min_qty": Decimal("0.01"),
        "tick_size": Decimal("0.01"),
        "lot_size": Decimal("0.01"),
    },
    {
        "exchange_code": "bybit",
        "base_symbol": "SOL",
        "quote_symbol": "USDT",
        "symbol": "SOLUSDT",
        "min_qty": Decimal("0.1"),
        "tick_size": Decimal("0.001"),
        "lot_size": Decimal("0.1"),
    },
    {
        "exchange_code": "bybit",
        "base_symbol": "DOGE",
        "quote_symbol": "USDT",
        "symbol": "DOGEUSDT",
        "min_qty": Decimal("1"),
        "tick_size": Decimal("0.00001"),
        "lot_size": Decimal("1"),
    },
    {
        "exchange_code": "bybit",
        "base_symbol": "1000PEPE",
        "quote_symbol": "USDT",
        "symbol": "1000PEPEUSDT",
        "min_qty": Decimal("1"),
        "tick_size": Decimal("0.000001"),
        "lot_size": Decimal("1"),
    },
]

SEED_SUBSCRIPTION_PLANS: list[dict[str, Any]] = [
    {
        "code": "free",
        "name": "Free",
        "price_monthly": Decimal("0.00"),
        "currency": "USD",
        "limits": {
            "max_watchlists": 3,
            "max_active_strategies": 1,
            "max_exchange_connections": 0,
            "realtime_signals": True,
            "backtest_depth_days": 7,
        },
        "features": {"virtual_trading": True, "ai_explanations": False},
        "is_active": True,
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_monthly": Decimal("29.00"),
        "currency": "USD",
        "limits": {
            "max_watchlists": 10,
            "max_active_strategies": 5,
            "max_exchange_connections": 3,
            "realtime_signals": True,
            "backtest_depth_days": 90,
        },
        "features": {"virtual_trading": True, "ai_explanations": True},
        "is_active": True,
    },
    {
        "code": "team",
        "name": "Team",
        "price_monthly": Decimal("99.00"),
        "currency": "USD",
        "limits": {
            "max_watchlists": 50,
            "max_active_strategies": 25,
            "max_exchange_connections": 15,
            "realtime_signals": True,
            "backtest_depth_days": 365,
        },
        "features": {"virtual_trading": True, "ai_explanations": True, "team_seats": True},
        "is_active": True,
    },
]

SEED_STRATEGIES: list[dict[str, Any]] = [
    {
        "code": "trend_pullback_continuation",
        "name": "Trend Pullback Continuation",
        "category": "trend-following",
        "description": "Continuation setup after a pullback into EMA support/resistance.",
        "risk_level": "medium",
        "is_active": True,
    },
    {
        "code": "volatility_squeeze_breakout",
        "name": "Volatility Squeeze Breakout",
        "category": "breakout",
        "description": "Breakout after volatility compression with volume confirmation.",
        "risk_level": "high",
        "is_active": True,
    },
    {
        "code": "liquidity_sweep_reversal",
        "name": "Liquidity Sweep Reversal",
        "category": "smart-money",
        "description": "Reversal after a sweep of recent swing liquidity.",
        "risk_level": "high",
        "is_active": True,
    },
]

SEED_STRATEGY_VERSIONS: list[dict[str, Any]] = [
    {
        "strategy_code": "trend_pullback_continuation",
        "version": "1.0",
        "status": "active",
        "default_params": {"min_history": 200, "watchlist_score": 50, "active_score": 70},
        "required_data": ["ema_20", "ema_50", "ema_200", "rsi_14", "atr_14", "volume_spike"],
    },
    {
        "strategy_code": "volatility_squeeze_breakout",
        "version": "1.0",
        "status": "active",
        "default_params": {"min_history": 60, "watchlist_score": 50, "active_score": 70},
        "required_data": [
            "bb_width_percentile",
            "donchian_high_20",
            "donchian_low_20",
            "volume_spike",
            "atr_14",
            "rsi_14",
        ],
    },
    {
        "strategy_code": "liquidity_sweep_reversal",
        "version": "1.0",
        "status": "active",
        "default_params": {"min_history": 30, "watchlist_score": 50, "active_score": 70},
        "required_data": [
            "swing_high",
            "swing_low",
            "upper_wick_ratio",
            "lower_wick_ratio",
            "volume_spike",
            "rsi_14",
            "atr_14",
        ],
    },
]

T = TypeVar("T")


@dataclass
class SeedSummary:
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    unchanged: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            "created": dict(sorted(self.created.items())),
            "updated": dict(sorted(self.updated.items())),
            "unchanged": dict(sorted(self.unchanged.items())),
        }


class _SeedTracker:
    def __init__(self) -> None:
        self.created: defaultdict[str, int] = defaultdict(int)
        self.updated: defaultdict[str, int] = defaultdict(int)
        self.unchanged: defaultdict[str, int] = defaultdict(int)

    def mark_created(self, table_name: str) -> None:
        self.created[table_name] += 1

    def mark_updated(self, table_name: str) -> None:
        self.updated[table_name] += 1

    def mark_unchanged(self, table_name: str) -> None:
        self.unchanged[table_name] += 1

    def summary(self) -> SeedSummary:
        return SeedSummary(
            created=dict(self.created),
            updated=dict(self.updated),
            unchanged=dict(self.unchanged),
        )


def bootstrap_postgres_seed(session: Session) -> SeedSummary:
    tracker = _SeedTracker()

    exchanges = _seed_exchanges(session, tracker)
    assets = _seed_assets(session, tracker)
    pairs = _seed_pairs(session, tracker, exchanges, assets)
    plans = _seed_subscription_plans(session, tracker)
    strategies = _seed_strategy_templates(session, tracker)
    _seed_strategy_versions(session, tracker, strategies)
    demo_user = _seed_demo_user(session, tracker)
    _seed_demo_profile(session, tracker, demo_user)
    _seed_demo_subscription(session, tracker, demo_user, plans["pro"])
    portfolio = _seed_demo_portfolio(session, tracker, demo_user)
    _seed_initial_balance(session, tracker, portfolio, assets["USDT"])
    _seed_default_watchlist(session, tracker, demo_user, pairs)

    session.flush()
    return tracker.summary()


def _seed_exchanges(session: Session, tracker: _SeedTracker) -> dict[str, MarketExchange]:
    exchanges: dict[str, MarketExchange] = {}
    for spec in SEED_EXCHANGES:
        values = {
            "code": spec["code"],
            "name": spec["name"],
            "type": spec["type"],
            "status": spec["status"],
            "api_base_url": spec["api_base_url"],
            "ws_base_url": spec["ws_base_url"],
            "metadata_": spec.get("metadata_", {}),
        }
        exchange = _upsert_one(
            session,
            MarketExchange,
            "market_exchanges",
            (MarketExchange.code == spec["code"],),
            values,
            tracker,
        )
        exchanges[exchange.code] = exchange
    return exchanges


def _seed_assets(session: Session, tracker: _SeedTracker) -> dict[str, MarketAsset]:
    assets: dict[str, MarketAsset] = {}
    for spec in SEED_ASSETS:
        values = {
            "symbol": spec["symbol"],
            "name": spec["name"],
            "asset_type": spec["asset_type"],
            "decimals": spec["decimals"],
            "coingecko_id": spec["coingecko_id"],
            "metadata_": spec.get("metadata_", {}),
        }
        asset = _upsert_one(
            session,
            MarketAsset,
            "market_assets",
            (MarketAsset.symbol == spec["symbol"],),
            values,
            tracker,
        )
        assets[asset.symbol] = asset
    return assets


def _seed_pairs(
    session: Session,
    tracker: _SeedTracker,
    exchanges: dict[str, MarketExchange],
    assets: dict[str, MarketAsset],
) -> dict[str, MarketPair]:
    pairs: dict[str, MarketPair] = {}
    for spec in SEED_PAIRS:
        exchange = exchanges[spec["exchange_code"]]
        base_asset = assets[spec["base_symbol"]]
        quote_asset = assets[spec["quote_symbol"]]
        values = {
            "exchange_id": exchange.id,
            "base_asset_id": base_asset.id,
            "quote_asset_id": quote_asset.id,
            "symbol": spec["symbol"],
            "status": "active",
            "min_qty": spec["min_qty"],
            "tick_size": spec["tick_size"],
            "lot_size": spec["lot_size"],
            "metadata_": {"market_type": "linear_perpetual", "source": "bootstrap"},
        }
        pair = _upsert_one(
            session,
            MarketPair,
            "market_pairs",
            (MarketPair.exchange_id == exchange.id, MarketPair.symbol == spec["symbol"]),
            values,
            tracker,
        )
        pairs[pair.symbol] = pair
    return pairs


def _seed_subscription_plans(session: Session, tracker: _SeedTracker) -> dict[str, SubscriptionPlan]:
    plans: dict[str, SubscriptionPlan] = {}
    for spec in SEED_SUBSCRIPTION_PLANS:
        plan = _upsert_one(
            session,
            SubscriptionPlan,
            "subscription_plans",
            (SubscriptionPlan.code == spec["code"],),
            dict(spec),
            tracker,
        )
        plans[plan.code] = plan
    return plans


def _seed_strategy_templates(session: Session, tracker: _SeedTracker) -> dict[str, StrategyTemplate]:
    strategies: dict[str, StrategyTemplate] = {}
    for spec in SEED_STRATEGIES:
        strategy = _upsert_one(
            session,
            StrategyTemplate,
            "strategy_templates",
            (StrategyTemplate.code == spec["code"],),
            dict(spec),
            tracker,
        )
        strategies[strategy.code] = strategy
    return strategies


def _seed_strategy_versions(
    session: Session,
    tracker: _SeedTracker,
    strategies: dict[str, StrategyTemplate],
) -> None:
    for spec in SEED_STRATEGY_VERSIONS:
        strategy = strategies[spec["strategy_code"]]
        config_schema = {
            "type": "object",
            "properties": {
                "min_history": {"type": "integer", "minimum": 1},
                "watchlist_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "active_score": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "additionalProperties": True,
            "required_data": spec["required_data"],
        }
        values = {
            "strategy_id": strategy.id,
            "version": spec["version"],
            "config_schema": config_schema,
            "default_params": spec["default_params"],
            "changelog": "Initial bootstrap version.",
            "status": spec["status"],
        }
        _upsert_one(
            session,
            StrategyVersion,
            "strategy_versions",
            (StrategyVersion.strategy_id == strategy.id, StrategyVersion.version == spec["version"]),
            values,
            tracker,
        )


def _seed_demo_user(session: Session, tracker: _SeedTracker) -> AppUser:
    values = {
        "email": DEMO_USER_EMAIL,
        "username": DEMO_USERNAME,
        "status": "active",
        "locale": "ru",
        "timezone": "Europe/Warsaw",
        "risk_profile": "balanced",
    }
    return _upsert_one(
        session,
        AppUser,
        "app_users",
        (AppUser.email == DEMO_USER_EMAIL,),
        values,
        tracker,
    )


def _seed_demo_profile(session: Session, tracker: _SeedTracker, user: AppUser) -> UserProfile:
    values = {
        "user_id": user.id,
        "display_name": "Demo Trader",
        "avatar_url": None,
        "onboarding_done": True,
        "settings": {
            "dashboard": {"default_route": "/dashboard/radar"},
            "notifications": {"websocket": True},
        },
    }
    return _upsert_one(
        session,
        UserProfile,
        "user_profiles",
        (UserProfile.user_id == user.id,),
        values,
        tracker,
    )


def _seed_demo_subscription(
    session: Session,
    tracker: _SeedTracker,
    user: AppUser,
    plan: SubscriptionPlan,
) -> UserSubscription:
    values = {
        "user_id": user.id,
        "plan_id": plan.id,
        "status": "active",
        "started_at": BOOTSTRAP_STARTED_AT,
        "current_period_start": BOOTSTRAP_STARTED_AT,
        "current_period_end": BOOTSTRAP_STARTED_AT + timedelta(days=30),
        "external_provider": BOOTSTRAP_EXTERNAL_PROVIDER,
        "external_id": BOOTSTRAP_DEMO_SUBSCRIPTION_ID,
    }
    return _upsert_one(
        session,
        UserSubscription,
        "user_subscriptions",
        (
            UserSubscription.external_provider == BOOTSTRAP_EXTERNAL_PROVIDER,
            UserSubscription.external_id == BOOTSTRAP_DEMO_SUBSCRIPTION_ID,
        ),
        values,
        tracker,
    )


def _seed_demo_portfolio(session: Session, tracker: _SeedTracker, user: AppUser) -> Portfolio:
    values = {
        "user_id": user.id,
        "type": "virtual",
        "name": DEMO_PORTFOLIO_NAME,
        "base_currency": "USDT",
        "status": "active",
    }
    return _upsert_one(
        session,
        Portfolio,
        "portfolios",
        (Portfolio.user_id == user.id, Portfolio.type == "virtual", Portfolio.name == DEMO_PORTFOLIO_NAME),
        values,
        tracker,
    )


def _seed_initial_balance(
    session: Session,
    tracker: _SeedTracker,
    portfolio: Portfolio,
    asset: MarketAsset,
) -> None:
    values = {
        "portfolio_id": portfolio.id,
        "asset_id": asset.id,
        "available": INITIAL_VIRTUAL_BALANCE,
        "locked": Decimal("0"),
    }
    _upsert_one(
        session,
        PortfolioBalance,
        "portfolio_balances",
        (PortfolioBalance.portfolio_id == portfolio.id, PortfolioBalance.asset_id == asset.id),
        values,
        tracker,
    )

    ledger_values = {
        "portfolio_id": portfolio.id,
        "asset_id": asset.id,
        "delta_available": INITIAL_VIRTUAL_BALANCE,
        "delta_locked": Decimal("0"),
        "reason": "bootstrap_initial_balance",
        "ref_type": "bootstrap",
        "ref_id": None,
    }
    _upsert_one(
        session,
        PortfolioBalanceLedger,
        "portfolio_balance_ledger",
        (
            PortfolioBalanceLedger.portfolio_id == portfolio.id,
            PortfolioBalanceLedger.asset_id == asset.id,
            PortfolioBalanceLedger.reason == "bootstrap_initial_balance",
            PortfolioBalanceLedger.ref_type == "bootstrap",
        ),
        ledger_values,
        tracker,
    )


def _seed_default_watchlist(
    session: Session,
    tracker: _SeedTracker,
    user: AppUser,
    pairs: dict[str, MarketPair],
) -> None:
    watchlist = _upsert_one(
        session,
        UserWatchlist,
        "user_watchlists",
        (UserWatchlist.user_id == user.id, UserWatchlist.name == DEFAULT_WATCHLIST_NAME),
        {
            "user_id": user.id,
            "name": DEFAULT_WATCHLIST_NAME,
            "is_default": True,
        },
        tracker,
    )
    for pair in pairs.values():
        _upsert_one(
            session,
            UserWatchlistPair,
            "user_watchlist_pairs",
            (
                UserWatchlistPair.watchlist_id == watchlist.id,
                UserWatchlistPair.pair_id == pair.id,
            ),
            {
                "watchlist_id": watchlist.id,
                "pair_id": pair.id,
            },
            tracker,
        )


def _upsert_one(
    session: Session,
    model: type[T],
    table_name: str,
    filters: tuple[Any, ...],
    values: dict[str, Any],
    tracker: _SeedTracker,
) -> T:
    instance = session.scalars(select(model).where(*filters)).one_or_none()
    if instance is None:
        instance = model(**values)
        session.add(instance)
        session.flush()
        tracker.mark_created(table_name)
        return instance

    changed = False
    for key, value in values.items():
        if getattr(instance, key) != value:
            setattr(instance, key, value)
            changed = True

    if changed:
        session.flush()
        tracker.mark_updated(table_name)
    else:
        tracker.mark_unchanged(table_name)
    return instance
