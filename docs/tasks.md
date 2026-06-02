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
8. [x] AUD-08: Improve breakout strategy with accepted breakout vs fakeout classifier.
9. [x] AUD-09: Improve trend_pullback with structural pullback and exhaustion filters.
10. [x] AUD-10: market-based exits.
11. [x] AUD-11: real execution readiness guardrails. Unblocked by completed
    AUD-01, AUD-02, AUD-03, AUD-04, AUD-05, AUD-06, AUD-07, AUD-08, AUD-09,
    and AUD-10.

AUD-11 does not enable live execution by default. It adds readiness checks,
protective-order requirements, idempotent order planning, partial-fill state,
and reconciliation guardrails before any non-dry-run adapter call.
`real_execution_enabled=false` remains the default, and a real adapter cannot
send a naked entry.

### AUD-11 Checklist

- [x] Add `RealExecutionReadinessService` after RiskGate and before adapter
  placement.
- [x] Require actionable signal status and `execution_allowed_real=true`.
- [x] Block missing structural stop, fallback stop, fallback-only targets, and
  incomplete production TradePlans.
- [x] Require protective stop plus take-profit or validated runner exit before
  entry placement.
- [x] Keep `real_execution_enabled=false` by default; dry-run remains the safe
  real adapter default.
- [x] Add role-scoped idempotency/client order checks and duplicate replay
  handling.
- [x] Represent partial fills through planned-order state and reconciliation
  metadata.
- [x] Add guarded cancel/replace and open-order adapter contracts.
- [x] Validate exchange qty/tick/min-notional rules before adapter placement.
- [x] Require fresh real account balance/equity, fresh fee rate TTL, futures
  liquidation projection, and position reconciliation for live adapters.

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

### AUD-08 Checklist

- [x] Extend volatility squeeze breakout state and TradePlan metadata with
  accepted breakout, fakeout risk, hold, retest, delta, OI, volume acceptance,
  failed breakout, alpha usage, and missing alpha source fields.
- [x] Add accepted breakout classifier using close outside range, close
  location, body quality, volume/VWAP acceptance, ATR expansion, optional
  delta/OI expansion, and post-breakout hold/retest quality.
- [x] Add fakeout risk classifier using wick close-back-inside, missing or weak
  delta/OI confirmation, low acceptance, large candle without hold, crowded
  funding/OI pressure, sweep-through-book without acceptance, and failed hold.
- [x] Keep delta/OI confirmations optional through params and disabled by
  default.
- [x] Add conservative retest mode for large or fakeout-prone breakouts with
  structured `retest_required_after_large_breakout` decision warning.
- [x] Add explicit failed-breakout invalidation conditions while preserving the
  legacy hard stop.
- [x] Record breakout classifier experiment params and grouped backtest metrics
  by entry model, accepted-breakout score bucket, and fakeout-risk score bucket.
- [x] Add targeted tests for accepted breakout, fakeout wick, large retest,
  missing alpha context, invalidation metadata, aggressive/conservative params,
  and backtest grouping.

### AUD-09 Checklist

- [x] Add structural trend-pullback zones with priority for VWAP/deviation,
  liquidity/session/PDH/PDL, HTF support/resistance, imbalance, and EMA
  fallback.
- [x] Add continuation confirmation metadata for reclaim/absorption, delta,
  volume, and configurable minimum continuation score.
- [x] Add exhaustion score, reasons, max threshold, and unified decision reason
  `trend_exhaustion`.
- [x] Add funding/OI crowded-trade penalty using `AlphaMarketContext` first and
  `Features` fallback, with hard block only by explicit config.
- [x] Add HTF/liquidity target-room preview metadata without changing AUD-10
  exit behavior.
- [x] Add structural invalidation metadata for loss of pullback zone, VWAP/zone
  acceptance against continuation, and swing/structure loss.
- [x] Record trend-pullback experiment params in backtest assumptions.
- [x] Add targeted tests for structural zones, EMA-only watchlist behavior,
  exhaustion, crowded funding/OI, missing alpha, HTF target room, invalidation,
  and backtest experiment params.

### AUD-10 Checklist

- [x] Add additive `TargetThesis` / `TargetSource` contract on
  `TradePlanTarget.thesis` without removing legacy TP fields.
- [x] Add service-layer `TargetResolverService` for ordered market target
  theses from `Features`, optional `AlphaMarketContext`, HTF S/R snapshots, and
  strategy metadata.
- [x] Filter target theses by direction and keep R-multiple targets explicit as
  `risk_multiple_fallback`.
- [x] Attach target thesis metadata in exit-plan enrichment while preserving
  legacy TP1/TP2 and runner behavior.
- [x] Keep production completeness blocked for fallback-only targets.
- [x] Keep risk management on `TradePlan` targets and handle unpriced runner
  instructions without falling back to risk-settings targets.
- [x] Record exit-policy experiment assumptions and grouped backtest metrics by
  exit policy, first/final target source, runner usage, and fallback target use.
- [x] Add targeted tests for resolver directionality, liquidity-pool source,
  R-multiple fallback metadata, production completeness, pipeline thesis
  attachment, and backtest exit-policy grouping.

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
