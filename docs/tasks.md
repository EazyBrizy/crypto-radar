# MVP Tasks

## Phase 1

- [x] connect ByBit public WebSocket adapter
- [x] stream trade price + volume through market services
- [x] calculate volume spike
- [x] deliver realtime updates to frontend clients

## Phase 2

- [x] implement breakout strategy
- [x] implement trend pullback strategy
- [x] implement liquidity sweep strategy
- [x] generate signals
- [x] expose API endpoint

## Phase 3

- [x] scoring system
- [x] store signals in DB
- [x] persist TradePlan snapshots
- [x] outcome labeling for persisted signals
- [x] strategy performance aggregation
- [x] EV gate / edge snapshot

## Phase 4

- [x] simple frontend radar
- [x] virtual trade lifecycle
- [x] shared virtual/real risk gate
- [x] real execution dry-run adapter boundary

## Patch 3.4 Documentation Status

- [x] Document canonical flow from market data through EV gate.
- [x] Add TradePlan operating playbook.
- [x] Add backtesting assumptions and metrics playbook.
- [x] Document virtual vs real risk gates.
- [x] Document heuristic score vs EV calibration.
- [x] Document operating rules for the three MVP strategies.

## Remaining Follow-Ups

- [ ] Keep `docs/interfaces.md` in sync before any schema/model/interface
  change.
- [ ] Add production real exchange adapter only after protective order and
  reconciliation rules are complete.
- [ ] Add real account equity/available-balance source for production sizing.
- [ ] Add projected liquidation-price calculation for new futures orders.
- [ ] Add orderbook stream/VWAP impact validation for lower-latency real gates.
- [ ] Add production fee-rate TTL, refresh observability, and non-Bybit fee
  adapters.
- [ ] Add per-symbol/per-timeframe strategy threshold review from backtests and
  forward outcomes.
- [ ] Add UI links from failed risk reasons to the exact setting or data source.

## Explicit DB Reminders

Keep these gaps visible before adding new read/write flows:

- [ ] `user_strategy_configs` exists as PostgreSQL table/model, but still needs full CRUD, service layer, API, and strategy settings UI.
- [ ] ClickHouse `market.orderbook_l2_deltas` and `market.orderbook_snapshots` exist, but the L2 order book connector/writer is not implemented yet.
- [x] ClickHouse `analytics.strategy_performance_daily` exists and has a strategy performance aggregation service/worker.
- [ ] PostgreSQL `external_exchange_orders`/`external_exchange_trades` and ClickHouse `analytics.external_trade_events` are ready, but wait for the real exchange import connector.
- [ ] AI/backtest/billing provider delivery endpoints are intentionally stub/501 for now; keep the existing PostgreSQL/ClickHouse infrastructure and replace only provider/workers later.
- [ ] Legacy empty ClickHouse `crypto_radar.*` tables still exist from old init scripts; current runtime must use `market.*` and `analytics.*`.
