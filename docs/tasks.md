# MVP Tasks

## Phase 1

- connect ByBit WebSocket
- stream price + volume
- calculate volume spike

## Phase 2

- implement breakout strategy
- generate signals
- expose API endpoint

## Phase 3

- scoring system
- store signals in DB

## Phase 4

- simple frontend radar

## Explicit DB Reminders

Keep these gaps visible before adding new read/write flows:

- [ ] `user_strategy_configs` exists as PostgreSQL table/model, but still needs full CRUD, service layer, API, and strategy settings UI.
- [ ] ClickHouse `market.orderbook_l2_deltas` and `market.orderbook_snapshots` exist, but the L2 order book connector/writer is not implemented yet.
- [ ] ClickHouse `analytics.strategy_performance_daily` exists, but needs an aggregator worker.
- [ ] PostgreSQL `external_exchange_orders`/`external_exchange_trades` and ClickHouse `analytics.external_trade_events` are ready, but wait for the real exchange import connector.
- [ ] AI/backtest/billing provider delivery endpoints are intentionally stub/501 for now; keep the existing PostgreSQL/ClickHouse infrastructure and replace only provider/workers later.
- [ ] Legacy empty ClickHouse `crypto_radar.*` tables still exist from old init scripts; current runtime must use `market.*` and `analytics.*`.
