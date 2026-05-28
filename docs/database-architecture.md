# Database Architecture

This document fixes the storage boundaries for implementation. Table-level
schemas should be added as versioned migrations when the table parameters are
finalized.

## Storage Boundaries

| Layer | Stores | Role |
| --- | --- | --- |
| PostgreSQL | users, subscriptions, settings, strategies, configs, signals as business entities, virtual trades, portfolios, trade journal, billing, audit | Transactional source of truth with FK, constraints, consistency, transactions, and access-control boundaries. |
| ClickHouse | market ticks, exchange trades, candles, order book snapshots/deltas, calculated indicators, signal events, historical analytics, PnL aggregates, backtest/runtime analytics | Analytical time-series store for high ingest and large scans using MergeTree-family engines. |
| Redis | hot prices, last signals, WebSocket fanout state, short-lived cache, rate limits, locks, lightweight queues/streams | Low-latency delivery and load reduction for UI/runtime paths. |
| NATS JetStream | normalized runtime events and durable worker handoff | Current project event bus. Kafka/Redpanda can replace or complement it later for larger event-log workloads. |

PostgreSQL answers: what is the current state of the system?
ClickHouse answers: what happened on the market and how do we analyze it?
Redis answers: what should be returned or pushed right now?

## Event Flow

```text
Exchanges
  -> market collectors / connectors
  -> normalizer
  -> NATS JetStream / Kafka-compatible bus
  -> ClickHouse: raw ticks, trades, candles
  -> Signal Engine: indicators, strategies
  -> signal generated
  -> PostgreSQL: signal state
  -> ClickHouse: signal analytics event
  -> Redis Pub/Sub/cache: instant UI delivery
```

Redis Pub/Sub is only for ephemeral fanout. Any event that must survive process
restart, be replayed, or be audited must also be stored in PostgreSQL,
ClickHouse, or the durable event bus.

## PostgreSQL Rules

- Use Alembic migrations from `backend/alembic`.
- Enable required extensions in the base migration:
  - `pgcrypto` for `gen_random_uuid()`.
  - `citext` for case-insensitive email/login identifiers.
  - `btree_gin` for useful combined GIN indexing patterns.
- Prefer explicit relational columns, FK, unique constraints, and check
  constraints for stable business data.
- Use `jsonb` only for genuinely dynamic payloads: strategy params, exchange
  metadata, signal payload snapshots, provider-specific billing metadata.
- Add GIN indexes only for `jsonb` fields that are actually queried.
- Use `timestamptz` for application timestamps.
- Prefer `numeric` for money, portfolio balances, fees, PnL, and order/trade
  quantities where exactness matters.
- Keep market time-series data out of PostgreSQL unless it is a small business
  snapshot needed for FK-backed workflows.

## Market Reference Tables

The first PostgreSQL dictionary block is implemented by migration
`202605280002_create_market_reference_tables`:

- `market_exchanges`: exchange catalogue, e.g. Binance, Bybit, OKX, Coinbase.
- `market_assets`: asset catalogue, e.g. BTC, ETH, USDT.
- `market_pairs`: exchange-specific tradable symbols linked to base/quote
  assets.

The `metadata` columns remain `jsonb` for provider-specific details. SQLAlchemy
models expose them as `metadata_` because `metadata` is reserved by the
declarative base.

## Users And Subscriptions

The user/access/subscription block is implemented by migration
`202605280003_create_user_subscription_tables`:

- `app_users`: account identity and default product preferences.
- `user_profiles`: one-to-one user profile with cascading delete from
  `app_users`.
- `subscription_plans`: plan catalogue with dynamic `limits` and `features`
  stored as `jsonb`.
- `user_subscriptions`: user-plan lifecycle records linked to users and plans.

## Exchange Connections

User exchange connections are implemented by migration
`202605280004_create_user_exchange_connections`.

`user_exchange_connections.key_ref` stores only the Vault/KMS secret reference.
Raw API keys and secrets must never be persisted in PostgreSQL. Exchange
permissions and provider-specific connection details use `jsonb`, while the ORM
exposes the database `metadata` column as `metadata_`.

## Strategies

Strategy templates, versions, and user configs are implemented by migration
`202605280005_create_strategy_tables`.

- `strategy_templates`: reusable base strategies such as breakout,
  trend-following, mean-reversion, smart-money, and scalping.
- `strategy_versions`: immutable version records with `config_schema`,
  `default_params`, changelog, and lifecycle status.
- `user_strategy_configs`: user-owned strategy settings linked to a concrete
  `strategy_versions.id`.

Signals must reference the strategy version that produced them. This prevents
old signals from being interpreted or backtested with newer strategy logic.

## Trading Signals

Business signal state and signal lifecycle events are implemented by migration
`202605280006_create_trading_signal_tables`.

- `trading_signals`: user-visible signal entity linked to strategy version,
  exchange, and market pair.
- `trading_signal_events`: append-only signal lifecycle history.

`trading_signal_events` is range-partitioned by `created_at`. PostgreSQL
requires primary/unique constraints on partitioned tables to include the
partition key, so the event table uses composite primary key `(id, created_at)`
and a default partition for safe inserts before monthly partitions are managed.

## Watchlists And Alerts

User watchlists and alert rules are implemented by migration
`202605280007_create_watchlist_alert_tables`.

- `user_watchlists`: user-owned named lists, with optional default marker.
- `user_watchlist_pairs`: composite-key membership table for market pairs.
- `user_alert_rules`: user-owned alert conditions scoped optionally to a pair
  and/or strategy version.

Alert condition payloads use `jsonb`; delivery channels use `text[]` with
`ARRAY['websocket']` as the default channel.

## Virtual Trading

Virtual trading tables are implemented by migration
`202605280008_create_virtual_trading_tables`.

- `portfolios`: virtual or live portfolio containers owned by users.
- `portfolio_balances`: current balance state per asset.
- `portfolio_balance_ledger`: append-only balance changes.
- `orders`: virtual/live order intents with user-scoped idempotency keys.
- `order_fills`: order execution records, including simulated fills.
- `positions`: open/closed/liquidated virtual or live positions.

Virtual orders, fills, and positions must never mutate market data. They are
simulated from external exchange data served by Redis/ClickHouse, so even
illiquid symbols do not get artificial candles from virtual activity.

## External Exchange Journal Import

Normalized real exchange orders and trades are implemented by migration
`202605280009_create_external_exchange_journal_tables`.

- `external_exchange_orders`: normalized imported exchange order state.
- `external_exchange_trades`: normalized imported exchange trade executions.

Raw exchange import events belong in ClickHouse for replay and analytics.
PostgreSQL keeps the normalized user journal records and idempotency constraints
per exchange connection.

## AI Signal Explanations

AI-generated signal explanations are reserved by migration
`202605280010_create_signal_ai_explanations`.

`signal_ai_explanations` stores provider/model identity, prompt hash,
Markdown explanation text, optional risk notes, and a cascade link to
`trading_signals`. AI logic is not implemented yet; this table only reserves
the durable business record shape.

## Notifications, Outbox, And Audit

Notifications, reliable event delivery, and audit records are implemented by
migration `202605280011_create_notifications_outbox_audit`.

- `notifications`: user-visible notification records with JSON payloads and
  unread state.
- `notification_deliveries`: per-channel delivery attempts linked to a
  notification.
- `outbox_events`: post-transaction event handoff table for reliable workers.
- `audit_log`: append-only user/system activity trail with `inet` IP storage.

`outbox_events` and `audit_log` are range-partitioned by `created_at` and use
default partitions. `notifications` and `audit_log` have Row-Level Security
enabled; concrete tenant policies should be added when the application starts
using a per-request database role or session variable.

The hot query indexes from the initial access plan are present:
`idx_orders_user_created`, `idx_orders_status`,
`idx_positions_user_status`, `idx_external_trades_user_time`,
`idx_notifications_user_read`, and `idx_outbox_pending`.

## ClickHouse Rules

- Keep DDL in `infra/clickhouse/init` for local bootstrap until a dedicated
  ClickHouse migration runner is introduced.
- Use `MergeTree` family tables with partitions based on event/candle time.
- Put low-cardinality dimensions such as `exchange`, `symbol`, `timeframe`,
  `strategy`, and `side` early in `ORDER BY` only when they match query filters.
- Use `DateTime64(3, 'UTC')` for exchange/runtime event timestamps.
- Store business entity IDs from PostgreSQL as strings/UUID-compatible values
  so ClickHouse rows can be correlated without FK semantics.

## ClickHouse Tables

The full market/analytics bootstrap DDL lives in
`infra/clickhouse/init/002_market_analytics.sql`.

- `market.raw_exchange_events`: raw exchange messages with 30-day TTL.
- `market.trades`: normalized exchange trades; exact deduplication belongs
  upstream on `(exchange, symbol, trade_id)`.
- `market.orderbook_l2_deltas`: level-2 book deltas with 14-day TTL.
- `market.orderbook_snapshots`: top-N or periodic book snapshots.
- `market.ohlcv_1m`, `market.ohlcv_5m`, `market.ohlcv_15m`,
  `market.ohlcv_1h`, `market.ohlcv_1d`: candle tables optimized for UI and
  strategy reads.
- `market.indicator_values`: calculated indicators and feature payloads.
- `analytics.signal_events`: signal lifecycle analytics.
- `analytics.strategy_performance_daily`: daily strategy aggregates.
- `analytics.virtual_trade_events`: simulated trading analytics.
- `analytics.external_trade_events`: imported real trade analytics.

## Redis Rules

- Cache keys must be reconstructable from source-of-truth data.
- Hot price and latest-signal keys should have TTL unless they represent
  connection/session state managed by the WebSocket layer.
- Pub/Sub channels are for immediate UI fanout only.
- Use streams/consumer groups or NATS JetStream for at-least-once processing.

## Redis Runtime Contract

Hot cache keys:

- `price:{exchange}:{symbol}`: last price, bid, ask, and timestamp; TTL 5-30s.
- `orderbook:{exchange}:{symbol}`: latest top-N book snapshot; TTL 1-5s.
- `signals:latest`, `signals:latest:{strategy_code}`,
  `signals:latest:{exchange}:{symbol}`: latest signal IDs or sorted sets.

Pub/Sub channels:

- `pubsub:signals:new`
- `pubsub:signals:update`
- `pubsub:prices:{exchange}:{symbol}`
- `pubsub:portfolio:{user_id}`

Redis Streams:

- `stream:market:trades`
- `stream:market:orderbook`
- `stream:signals:generated`
- `stream:orders:virtual`
- `stream:notifications`

Consumer groups:

- `cg:clickhouse-writer`
- `cg:signal-engine`
- `cg:notification-service`
- `cg:websocket-gateway`

Rate limits and locks:

- `rate:user:{user_id}:api`
- `rate:ip:{ip}:auth`
- `rate:exchange:{exchange}:requests`
- `lock:portfolio:{portfolio_id}`
- `lock:signal:{signal_id}:confirm`
- `lock:exchange-sync:{connection_id}`

## Partitioning Plan

PostgreSQL partitioned now:

- `trading_signal_events`: monthly range partitions by `created_at`.
- `outbox_events`: monthly range partitions by `created_at`.
- `audit_log`: monthly range partitions by `created_at`.

PostgreSQL partition candidates before heavy production ingest:

- `portfolio_balance_ledger`: monthly range partitions by `created_at`.
- `order_fills`: monthly range partitions by `filled_at`.
- `external_exchange_trades`: monthly range partitions by `traded_at`.

`external_exchange_trades` currently keeps a global unique constraint on
`(connection_id, exchange_trade_id)`. PostgreSQL unique constraints on
partitioned tables must include the partition key, so partitioning that table
requires either upstream/global idempotency enforcement or changing the
database uniqueness shape.

ClickHouse partition keys are encoded directly in the DDL: raw exchange events
and order book deltas by day, trades/candles/indicators/signal/trade analytics
by month.

## MVP Storage Cut

PostgreSQL MVP:

- `app_users`, `subscription_plans`, `user_subscriptions`
- `market_exchanges`, `market_assets`, `market_pairs`
- `strategy_templates`, `strategy_versions`, `user_strategy_configs`
- `trading_signals`, `trading_signal_events`
- `portfolios`, `portfolio_balances`, `portfolio_balance_ledger`
- `orders`, `order_fills`, `positions`
- `user_watchlists`, `user_watchlist_pairs`
- `notifications`, `outbox_events`, `audit_log`

ClickHouse MVP:

- `market.raw_exchange_events`, `market.trades`
- `market.ohlcv_1m`, `market.ohlcv_5m`, `market.ohlcv_15m`,
  `market.ohlcv_1h`
- `market.indicator_values`
- `analytics.signal_events`, `analytics.virtual_trade_events`
- `analytics.strategy_performance_daily`

Redis MVP:

- `price:{exchange}:{symbol}`
- `orderbook:{exchange}:{symbol}`
- `signals:latest`, `signals:latest:{exchange}:{symbol}`
- `stream:market:trades`
- `stream:signals:generated`
- `stream:orders:virtual`
- `pubsub:signals:new`
- `pubsub:portfolio:{user_id}`
- `rate:user:{user_id}:api`

## Final Responsibility Split

PostgreSQL remains the business state and transaction source of truth:
users, subscriptions, exchange connections, strategies, signal state,
virtual/live order state, balances, normalized user journals, notifications,
audit, and outbox.

ClickHouse remains the analytical and historical store: raw exchange events,
market trades, order books, candles, indicators, market features, signal
events, backtests, PnL aggregates, and runtime performance analytics.

Redis remains the low-latency runtime layer: hot prices, latest order books,
latest signals, WebSocket fanout, rate limits, locks, and short-lived dashboard
cache.

Do not store market ticks/order books/candles in PostgreSQL. Do not use
ClickHouse as the only source of truth for user transactions. Do not treat
Redis as durable storage.

## Implementation Checklist For New Tables

1. Decide the owning storage layer: PostgreSQL for state, ClickHouse for
   analytics/time-series, Redis for hot ephemeral access.
2. Define IDs, lifecycle states, timestamps, and idempotency keys.
3. Add PostgreSQL DDL through Alembic or ClickHouse DDL through
   `infra/clickhouse/init`.
4. Add SQLAlchemy models only for PostgreSQL business entities.
5. Add repository/service boundaries before API handlers depend on persistence.
6. Add indexes from access patterns, not from every column.
7. Add tests for lifecycle transitions, constraints, and repository behavior.
