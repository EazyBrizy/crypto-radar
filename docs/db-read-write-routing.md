# Database Read/Write Routing Cheat Sheet

Use this file as the implementation guardrail when adding repositories,
workers, consumers, API handlers, and dashboard reads.

## PostgreSQL

PostgreSQL is the transactional source of truth. Write durable business state
here.

Write here:

- users
- profiles
- subscriptions
- subscription plans
- exchange API connections
- strategy templates and strategy versions
- user strategy configs
- watchlists
- signals as business entities
- signal status
- user-confirmed signal entries
- virtual orders
- virtual positions
- current balances
- balance ledger entries
- normalized imported user trades
- notifications
- audit log
- outbox events

Read from here when the UI or service needs current authoritative state,
ownership checks, FK-backed relations, idempotency, transactions, or access
control decisions.

## ClickHouse

ClickHouse is the analytical time-series and historical event store. Write
large append-only market/runtime analytics here.

Write here:

- raw exchange websocket messages
- trades and ticks
- order book deltas
- order book snapshots
- candles
- indicators
- market features
- signal events
- strategy analytics
- virtual trading analytics
- real trading analytics
- backtest results
- aggregated PnL metrics
- runtime performance metrics

Read from here for historical charts, market scans, indicators, analytics,
backtests, PnL aggregates, performance dashboards, and large time-range scans.

## Redis

Redis is the low-latency runtime layer. Treat it as hot, ephemeral, and
rebuildable from PostgreSQL/ClickHouse/event streams.

Write here:

- latest prices
- best bid/ask
- top-N order book
- latest signals
- temporary signal rankings
- WebSocket channels
- Redis Streams events
- rate limits
- distributed locks
- short-lived user dashboard cache

Read from here for immediate UI fanout, hot dashboard widgets, short-lived
cache, lock checks, rate-limit checks, and stream consumers.

## Hard Rules

- Do not write ticks, order books, or candles to PostgreSQL.
- Do not use ClickHouse as the only source of truth for users, subscriptions,
  balances, order status, or other user transactions.
- Do not treat Redis as durable storage.
- If data must be correct after restart, it must land in PostgreSQL,
  ClickHouse, or a durable event bus.

## Open Implementation Reminders

Do not treat these as missing schema. The schema is ready; the runtime pieces
below are intentionally pending and must be wired before claiming full coverage:

- `user_strategy_configs`: add full CRUD, service boundary, API endpoints, and
  frontend strategy settings UI.
- `market.orderbook_l2_deltas` and `market.orderbook_snapshots`: add a real L2
  order book connector/writer. The current market persistence only writes a
  Redis placeholder for top-of-book/orderbook cache.
- `analytics.strategy_performance_daily`: add an aggregator worker that rolls
  signal/trade outcomes into daily strategy metrics.
- `external_exchange_orders`, `external_exchange_trades`, and
  `analytics.external_trade_events`: wire the real exchange import connector.
- AI explanation generation, backtest execution, and billing provider delivery:
  keep current stub/501 contracts until the external model, runner, and provider
  integrations are implemented.
- Legacy ClickHouse `crypto_radar.*` tables are old empty init artifacts. Current
  code must continue to write/read `market.*` and `analytics.*`.
