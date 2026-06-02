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

## Global Update 3 / Audit Roadmap

AUD work must be handled as small PR-sized patches. Do not mix neighboring
AUD tasks unless an explicit dependency requires it.

LAB prerequisites:

- [x] LAB-01: Implement synchronous Strategy Test Lab batch/matrix API on top
  of `ProductionBacktestRunner.run_detailed`. This is a prerequisite for
  AUD-03 baseline work.
- [x] LAB-02: Baseline current strategies through Strategy Test Lab with
  reproducible JSON output and explicit `no_data` / `insufficient_data`
  statuses.

AUD-02 and later AUD patches must compare strategy, fallback, pipeline,
candle-state, and exit changes against the saved LAB-02 baseline artifact.

1. [x] AUD-01: contract cleanup after RR and Strategy Test Lab.
2. [x] AUD-02: Remove production fallback stop/TP while keeping research compatibility.
3. [x] AUD-03: Separate open candle preview signals from closed candle actionable signals.
4. [x] AUD-04: Refactor StrategySignalPipeline services without behavior regression.
5. [x] AUD-05: Introduce unified SignalDecisionSnapshot contract across pipeline/API/UI.
6. [x] AUD-06: Add AlphaMarketContext and smart-money/orderflow features.
7. [x] AUD-07: Improve liquidity_sweep_reversal with smart-money/orderflow context.
8. [ ] AUD-08: reserved alpha/context calibration follow-up if needed.
9. [ ] AUD-09: strategy upgrades.
10. [ ] AUD-10: market-based exits.
11. [ ] AUD-11: real execution readiness. Blocked by AUD-01, AUD-02, AUD-03,
    AUD-04, AUD-05, AUD-06, AUD-07, AUD-08, AUD-09, and AUD-10.

AUD-11 must not add real execution paths until research/backtest evidence,
strategy calibration, fallback cleanup, candle-state separation, pipeline
cleanup, decision snapshots, market context, strategy upgrades, and
market-based exits are complete.

### AUD-06 Checklist

- [x] Add optional alpha schemas: `RecentTrade`, `RecentTradesAggregate`,
  `DeltaFeatures`, `OrderBookAlphaFeatures`, `DerivativeAlphaFeatures`,
  `LiquidityPoolFeatures`, `VwapReactionFeatures`, and `AlphaMarketContext`.
- [x] Build alpha context in `AlphaMarketContextService` without strategy-side
  API/DB/exchange calls.
- [x] Pass optional alpha context from `MarketScanner` to `StrategyEngine` and
  `StrategyEvaluationContext`.
- [x] Keep missing alpha data explicit through `data_quality.missing_sources`.
- [x] Keep backtests free of live alpha data and record
  `alpha_context_available=false` metadata.
- [x] Add targeted tests for schema optionality, trade delta aggregation,
  orderbook imbalance/depth walls, derivative missing-history behavior,
  scanner handoff, and backtest no-alpha operation.

### AUD-07 Checklist

- [x] Extend liquidity sweep setup metadata with obvious-liquidity, reclaim,
  absorption, CVD divergence, OI/liquidation flush, failed continuation, target
  room, alpha usage, and missing-source fields.
- [x] Score session, previous-day, range, swing/equal, high-volume, and alpha
  liquidity-pool levels instead of relying on a single wick pattern.
- [x] Require reclaim/acceptance context for actionable reversal; continued
  breakout is rejected/watchlist research context.
- [x] Use optional `AlphaMarketContext` for absorption, CVD, orderbook, OI, and
  liquidation evidence while preserving explicit missing-alpha metadata.
- [x] Prefer market targets and target thesis metadata when available; keep
  fallback targets explicit.
- [x] Add threshold experiment params for Strategy Lab/backtests without
  fabricating baseline or alpha results.
- [x] Add targeted tests for reclaim/absorption, CVD divergence, missing alpha,
  OI boost, target room, failed continuation, and target metadata.

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
