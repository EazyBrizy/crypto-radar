# DATABASE

Codex guide for current persistence. PostgreSQL is the source of truth for app state; Redis and ClickHouse are supporting stores.

## PostgreSQL

Models live in `backend/app/models/`. Migrations live in `backend/alembic/versions/`.

### Identity And Subscription

- `app_users`: application user root record and stable user id.
- `user_auth_identities`: external auth provider identities linked to users.
- `user_profiles`: user settings, preferences, and risk settings payloads.
- `subscription_plans`: available plan definitions.
- `user_subscriptions`: user plan state and billing lifecycle.

### Exchange Connections

- `user_exchange_connections`: user exchange connection metadata, environment, order placement mode, status, soft delete, and safety flags.

### Market Reference

- `market_exchanges`: supported exchange metadata.
- `market_assets`: asset metadata.
- `market_pairs`: tradable pair universe, liquidity fields, and scanner selection metadata.
- `market_derivative_snapshots`: current derivative context such as funding/open-interest snapshots.

### Strategies

- `strategy_templates`: strategy definitions.
- `strategy_versions`: versioned strategy metadata.
- `user_strategy_configs`: per-user strategy runtime settings, pairs, timeframes, and risk settings.
- `strategy_test_runs`: strategy testing run metadata and report payloads. Runtime columns include `test_type`, `summary`, `runtime_state`, and `last_heartbeat_at`; valid statuses are `queued`, `running`, `completed`, `failed`, `cancelled`, and `stopping`. `runtime_state` is the backend-owned forward/front-test state bag for counters and display status, while `last_heartbeat_at` is the stale-run source for active-run gating.

### Signals And Pending Entry

- `trading_signals`: durable signal snapshots and current signal lifecycle state.
- `trading_signal_events`: partitioned signal event history.
- `signal_outcomes`: tracked signal outcome state after candles close.
- `signal_ai_explanations`: generated explanations for signals.
- `pending_entry_intents`: accepted entry-zone intents, trade-plan snapshots, execution profile snapshots, status, idempotency, and reconfirmation state.
- `trade_invalidation_actions`: user/system actions taken after trade invalidation alerts.

### Portfolio, Orders, Positions

- `portfolios`: user/mode portfolio root.
- `portfolio_balances`: current balances by portfolio/asset.
- `portfolio_balance_ledger`: balance changes.
- `orders`: internal order records.
- `order_fills`: fills linked to orders.
- `positions`: virtual/real position lifecycle records.
- `external_exchange_orders`: imported or synced exchange orders.
- `external_exchange_trades`: imported or synced exchange trades.

### Risk

- `risk_decisions`: persisted risk gate decisions and lifecycle traces.
- `position_risk_snapshots`: position risk snapshots.
- `exchange_instrument_rules`: exchange min/max size, notional, leverage, tick/step rules.
- `asset_risk_groups`: correlation/risk grouping for assets.
- `risk_protection_state`: close-only/protection state after risk limit events.

### Watchlists And Alerts

- `user_watchlists`: user watchlist containers.
- `user_watchlist_pairs`: pairs in watchlists.
- `user_alert_rules`: alert rules for prices/signals.

### Notifications And Events

- `notifications`: user notifications.
- `notification_deliveries`: per-channel delivery state.
- `outbox_events`: partitioned durable app event log for later publishing/retry.
- `audit_log`: partitioned audit trail.

## Redis

Redis is not the canonical app database. Current purposes:

- Hot signal cache and latest sorted sets from `RedisSignalHotStore`.
- Notification stream and notification Pub/Sub.
- Realtime Pub/Sub fanout channel for WebSocket/SSE delivery.
- Short-lived snapshots/cache where services explicitly use `backend/app/core/redis_client.py`.

Do not store durable trading state only in Redis.

## ClickHouse

ClickHouse stores high-volume market and analytics data. Init SQL lives in `infra/clickhouse/init/`.

- `crypto_radar.market_trades`, `crypto_radar.candles`, `crypto_radar.generated_signals`: baseline market/signal analytics tables.
- `market.raw_exchange_events`, `market.trades`, `market.orderbook_l2_deltas`, `market.orderbook_snapshots`, `market.liquidity_snapshots`: raw and derived market streams.
- `market.ohlcv_1m`, `market.ohlcv_5m`, `market.ohlcv_15m`, `market.ohlcv_1h`, `market.ohlcv_4h`, `market.ohlcv_1d`: OHLCV series.
- `market.indicator_values`: feature/indicator values.
- `analytics.signal_events`, `analytics.strategy_performance_daily`, `analytics.virtual_trade_events`, `analytics.external_trade_events`: analytics events.
- `analytics.backtest_results`, `analytics.strategy_test_trades`, `analytics.strategy_test_metrics`: testing and reporting analytics.

Do not use ClickHouse as the source of truth for user actions, positions, orders, or safety decisions.

## NATS, Outbox, Realtime

- NATS JetStream is available in local/deploy infra and configured through `NATS_URL`.
- PostgreSQL `outbox_events` is the durable event boundary for future/retryable publishing.
- Current realtime delivery uses Redis Pub/Sub and FastAPI WebSocket/SSE gateway.
- If adding a NATS publisher, consume `outbox_events`, publish idempotently, update `status`, `attempts`, `next_retry_at`, and `published_at`, and test replay/retry behavior.

## Migration Rules

- Never change PostgreSQL schema without an Alembic migration.
- Keep SQLAlchemy models and migrations aligned.
- Use explicit constraints, indexes, and JSONB defaults where existing models do.
- Partitioned tables must keep the partition key in the primary key.
- Data migrations must be idempotent and safe to rerun in development.
- Do not call `Base.metadata.create_all()` for application startup.
- Run migrations before backend startup in local/dev scripts:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
```

`alembic current` must match `alembic heads`. Backend startup warns when it can verify that PostgreSQL is not at Alembic head, but the warning is diagnostic only; run `alembic upgrade head` before local scanner or virtual-trading checks.
