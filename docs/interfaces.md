# System Flow

MarketData → Features → StrategySignal → TradePlan → RiskGate → Execution

## Backtest Runner v1

Production backtests replay closed historical candles through the same service
pipeline used by live signal generation:

Historical candles -> FeatureEngine -> StrategyEngine/StrategySignalPipeline ->
RiskGate -> virtual execution/lifecycle simulation -> metrics.

`HistoricalCandleProvider` is the service boundary for loading candles:

```python
class HistoricalCandleProvider(Protocol):
    async def load_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[OHLCVCandle]:
        ...
```

Providers must return only closed candles ordered by `open_time` and must not
include candles outside `[start_at, end_at]`.

`BacktestRunRequest.params` may carry optional backtest configuration such as
`warmup_candles`, `rolling_window_candles`, `leverage`, `risk_settings`, and
strategy params. Existing top-level `fee_rate` and `slippage_bps` remain the
execution cost inputs.

`BacktestResultResponse` keeps the existing top-level fields and adds v1
analytics in `metrics`:

- `trades_count`, `wins`, `losses`, `winrate`
- `avg_win_r`, `avg_loss_r`, `expectancy_r`, `profit_factor`
- `max_drawdown_pct`
- `fees_total`, `slippage_total`, `funding_total`
- `avg_bars_in_trade`, `mfe_r_avg`, `mae_r_avg`
- `tp1_rate`, `stop_rate`
- `by_strategy`, `by_regime`

No-data failures must surface explicit `no_historical_data` or
`not_enough_data` errors instead of `not_implemented` when a runner is
configured.

`TradePlan` is a backward-compatible v1 signal contract generated from the
legacy signal entry/stop/target fields. Existing signal fields remain available:
`entry_min`, `entry_max`, `stop_loss`, `take_profit_1`, `take_profit_2`,
`risk_reward`, `first_target_rr`, `final_target_rr`, `selected_rr`,
`selected_rr_target`, and `min_rr_ratio`.

`TradePlan` is persisted in `features_snapshot.trade_plan` and restored to
`StrategySignal.trade_plan` / `RadarSignal.trade_plan` when present.

Strategy trade plans are level-aware when strategy context exposes structure:

- `trend_pullback_continuation` uses an EMA20/EMA50 pullback-zone entry model,
  structure-aware TP1/TP2, and may add `time_stop_bars` in
  `TradePlan.risk_rules.metadata`.
- `volatility_squeeze_breakout` records `aggressive_breakout` or
  `conservative_retest` entry metadata and stores the measured move as an
  executable `TradePlanTarget` when enabled.
- `liquidity_sweep_reversal` uses range midpoint and opposite boundary targets
  where available.

Strategy runtime params include:

- `trend_pullback_continuation.entry_model`
- `trend_pullback_continuation.max_overextension_atr`
- `trend_pullback_continuation.require_htf_alignment`
- `trend_pullback_continuation.time_stop_bars`
- `volatility_squeeze_breakout.allow_aggressive_entry`
- `volatility_squeeze_breakout.require_retest_after_large_candle`
- `volatility_squeeze_breakout.large_candle_body_atr`
- `volatility_squeeze_breakout.measured_move_target_enabled`
- `volatility_squeeze_breakout.oi_expansion_threshold`
- `volatility_squeeze_breakout.oi_expansion_bonus`
- `volatility_squeeze_breakout.oi_no_expansion_penalty`
- `liquidity_sweep_reversal.require_reclaim`
- `liquidity_sweep_reversal.require_absorption`
- `liquidity_sweep_reversal.max_obstacle_distance_r`
- `liquidity_sweep_reversal.oi_flush_threshold`
- `liquidity_sweep_reversal.oi_flush_bonus`
- `trend_pullback_continuation.funding_warning_threshold`
- `trend_pullback_continuation.funding_block_threshold`
- `trend_pullback_continuation.crowded_oi_change_threshold`
- `trend_pullback_continuation.crowded_oi_penalty`

`Features` may expose intraday range context for level-aware strategies:
`session_high`, `session_low`, `previous_day_high`, and `previous_day_low`.

`Features` may expose derivative context when a hot derivative snapshot is
available:

- `funding_rate`: current exchange funding rate;
- `oi_change`: fractional open-interest change versus the previous derivative
  snapshot, or `None` when current or previous open interest is unavailable.

`DerivativeMarketSnapshot` keeps backward-compatible market context fields and
may include:

- `open_interest`
- `open_interest_value`
- `oi_change`

`oi_change` is calculated only from real exchange-provided open interest:
`(current_open_interest - previous_open_interest) / previous_open_interest`.
It remains `None` when the exchange omits open interest or no previous open
interest exists.

Risk gate consumes `RiskContext.trade_plan` when it is present. Take-profit
precedence is:

1. `manual_take_profit_price` explicit override;
2. `trade_plan.targets` from the signal;
3. risk-settings generated `calculate_take_profit_plan` fallback only when the
   signal has no `trade_plan`.

Malformed `TradePlan` take-profit data must fail the risk decision instead of
silently falling back to risk-settings targets. Validation rules:

- long targets must be above entry;
- short targets must be below entry;
- stop loss must be on the risk side of entry;
- target `r_multiple` is recalculated from actual entry/stop/target prices;
- each executable target must have `close_percent > 0`;
- total executable `close_percent` must not exceed 100.

`TakeProfitPlan.source` records `manual_override`, `trade_plan`,
`trade_plan_invalid`, or `risk_settings`. `TakeProfitPlan.selected_rr` /
`selected_rr_target` record the RR actually used by risk checks; for
`trade_plan`, `selected_rr_target` is read from
`TradePlan.risk_rules.selected_rr_target` when provided.

## Virtual Trade Lifecycle v1

`VirtualTrade` keeps the legacy execution fields (`size_usd`, `quantity`,
`stop_loss`, `take_profit`, `fees`, `pnl`, `close_reason`) for backward
compatibility. `take_profit` remains `list[float]` and continues to represent
the legacy target price list.

Lifecycle-aware virtual trades also expose:

- `initial_quantity`, `remaining_quantity`, `closed_quantity`
- `initial_size_usd`, `remaining_size_usd`
- `current_stop_loss`, `stop_moved_to_breakeven`, `trailing_active`
- `realized_pnl`, `unrealized_pnl`, `exit_fees`
- `target_states: list[VirtualTradeTargetState]`
- `lifecycle_events: list[VirtualTradeLifecycleEvent]`

`target_states` records executable take-profit targets from
`VirtualExecutionReport.take_profit_plan` when available. Legacy virtual trades
without `target_states` must still work by using the final legacy
`take_profit` price as a full-close target.

Lifecycle close reasons extend the legacy set with
`partial_take_profit`, `breakeven_stop`, `trailing_stop`, and `time_stop`.
Partial take-profit events keep the trade open, update remaining/closed
quantities, account proportional entry fees plus exit fees in `realized_pnl`,
and append a lifecycle event. Final closes set legacy `pnl` / `pnl_percent`
from accumulated lifecycle PnL.

Lifecycle state is persisted through the virtual trade metadata snapshot stored
on the entry order. No database migration is required for v1.

## Signal Outcome Labeling v1

`SignalOutcome` records the observed result of every relevant strategy signal,
independent from whether a user confirmed a real or virtual trade. Outcomes are
stored in `signal_outcomes` and are keyed one-to-one by `signal_id` to avoid
duplicate tracking for refreshed signals.

Tracking is created only after a strategy signal is persisted and all of these
conditions hold:

- `score >= settings.signal_outcome_tracking_min_score`;
- entry zone, stop loss, and at least one directional target are valid;
- no outcome exists for the same persisted signal.

`SignalOutcome.status` values:

- `tracking`
- `entry_touched`
- `tp1`
- `tp2`
- `tp3`
- `stop_loss`
- `expired`
- `invalidated`
- `time_stop`

`SignalOutcome.outcome` values:

- `win`
- `loss`
- `breakeven`
- `expired`
- `invalidated`
- `open`

Closed candles update open outcomes by `exchange`, `symbol`, and `timeframe`.
Entry touch is detected when candle high/low intersects the signal entry zone
for both long and short signals. After entry is touched, MFE and MAE are stored
in R units using the persisted entry price and stop distance. `bars_to_entry`
and `bars_to_outcome` count processed closed candles since tracking started.

Target/stop collisions inside the same candle use
`settings.signal_outcome_same_candle_resolution`. The v1 default is
`stop_first`; supported values are `stop_first`, `target_first`, and
`ignore_ambiguous`.

Expiry before entry closes the outcome as `expired` with `realized_r = 0`.
Time stop metadata may be supplied by `trade_plan.metadata`,
`trade_plan.risk_rules.metadata`, or `trade_plan.invalidation.metadata` via
`time_stop`, `time_stop_at`, `expires_at`, `at`, or `max_holding_seconds`.

## Strategy Performance Aggregator v1

`StrategyPerformanceService.aggregate_daily` builds strategy analytics from
closed `SignalOutcome` records and writes daily rows to
`analytics.strategy_performance_daily`.

Daily rows are grouped by:

- `date`
- `exchange`
- `symbol`
- `timeframe`
- `strategy`
- `strategy_version`
- `market_regime`
- `score_bucket`
- `direction`

`score_bucket` values are:

- `0-49`
- `50-59`
- `60-69`
- `70-79`
- `80-89`
- `90-100`

Daily metrics are:

- `sample_size`
- `trades_count`
- `signals_count`
- `wins_count`
- `losses_count`
- `entry_touch_rate`
- `winrate`
- `tp1_rate`
- `tp2_rate`
- `stop_rate`
- `invalidation_rate`
- `avg_win_r`
- `avg_loss_r`
- `expectancy_r`
- `profit_factor`
- `max_drawdown_r`
- `median_bars_to_entry`
- `median_bars_to_outcome`
- `avg_mfe_r`
- `avg_mae_r`
- `fees_bps`
- `slippage_bps`

`StrategyPerformanceService.get_edge_profile` returns a
`StrategyEdgeProfile` for a requested strategy/exchange/symbol/timeframe with
optional market regime and score. Lookup order is:

1. exact `strategy + exchange + symbol + timeframe + market_regime + score_bucket`;
2. fallback `strategy + timeframe + market_regime`;
3. fallback `strategy` global.

The minimum sample threshold is configured by
`settings.strategy_performance_min_sample_size`. Results with data below that
threshold return `confidence = "low"`. No matching data returns
`confidence = "insufficient_sample"`.

## Edge Calibration / EV Gate v1

`StrategySignal` and `RadarSignal` expose optional `edge:
SignalEdgeSnapshot | None` for historical/forward-performance calibration.
The heuristic `score` remains backward-compatible and is not recalculated by
the EV gate.

`SignalEdgeSnapshot` fields:

- `status`: `unknown`, `positive`, `negative`, or `insufficient_sample`
- `sample_size`
- `min_sample_size`
- `winrate`
- `avg_win_r`
- `avg_loss_r`
- `expectancy_r`
- `expectancy_after_costs_r`
- `profit_factor`
- `confidence_score`
- `source`: `outcome`, `backtest`, `mixed`, or `none`
- `score_bucket`
- `metadata`

`EdgeCalibrationService.evaluate_signal_edge(signal)` reads
`StrategyPerformanceService.get_edge_profile()` and calculates:

```python
expectancy_r = winrate * avg_win_r - (1 - winrate) * abs(avg_loss_r)
expectancy_after_costs_r = expectancy_r - estimated_costs_r
```

`estimated_costs_r` is derived from the profile cost bps and the signal
entry/stop distance when available; otherwise it is recorded as `0` with
metadata indicating that R-based cost conversion was unavailable.

`RiskManagementSettings` adds:

- `real_requires_positive_edge: bool = True`
- `edge_min_sample_size: int = 50`
- `min_expectancy_after_costs_r: float = 0.05`

Real execution must be blocked when `real_requires_positive_edge` is enabled
and any of these conditions is true:

- signal edge is missing;
- edge status is not `positive`;
- edge `sample_size` is below `edge_min_sample_size`;
- `expectancy_after_costs_r` is missing or not greater than
  `min_expectancy_after_costs_r`.

Virtual execution does not hard-block on explicit unknown, insufficient, or
weak edge snapshots, but the risk decision warns:
`Edge is insufficient/unknown; virtual-only recommended.`

## Real Execution Adapter v1

Real execution keeps the existing backend risk-gate boundary and now adds a
safe adapter layer before any production exchange integration:

```text
RealExecutionService -> ExchangeExecutionAdapter -> DryRunExecutionAdapter
```

`ExchangeExecutionAdapter` is an async protocol with these methods:

- `place_order(order)`
- `place_protective_stop(order)`
- `place_take_profit(order)`
- `cancel_order(exchange, symbol, client_order_id)`
- `get_order(exchange, symbol, client_order_id)`
- `get_position(exchange, symbol)`

The default adapter is `DryRunExecutionAdapter`. It never sends exchange orders.
It returns the planned entry, protective stop, and take-profit orders with
stable `client_order_id` values and idempotency keys.

`RealExecutionResult.status` keeps the existing `not_implemented` and
`risk_failed` values and adds:

- `dry_run`: the risk gate passed, a complete order plan was built, and the
  dry-run adapter returned planned orders;
- `submitted`: reserved for a future real adapter after explicit implementation.

`RealExecutionResult` remains backward compatible and may include:

- `execution_plan`: full real execution plan;
- `planned_orders`: flattened list of planned adapter orders;
- `idempotency_key`: stable key for the same signal/order intent;
- `adapter`: adapter name such as `dry_run`;
- `validation_errors`: execution-plan validation failures when present.

`ExecutionPlannedOrder` records:

- `role`: `entry`, `protective_stop`, or `take_profit`;
- `side`: exchange order side, `buy` or `sell`;
- `order_type`: `market`, `limit`, `stop`, or `take_profit`;
- `quantity`, optional `price`, optional `stop_price`;
- `reduce_only` for protective stop and take-profit orders;
- optional `close_percent`;
- `client_order_id`, `idempotency_key`, `status`, and `metadata`.

Real execution must not place an order when no adapter is configured. In that
case it returns `not_implemented` after the risk decision and execution plan are
available. If exchange rule step sizes are available, quantity must align with
`qty_step` and entry/stop/take-profit prices must align with `tick_size` before
adapter methods are called.

## Real Position Reconciliation v1

After a real execution adapter submits orders, exchange order/position state is
the source of truth for local live `Order` and `Position` records.

`RealPositionSyncWorker` periodically uses a configured real sync client to:

- fetch exchange open orders;
- fetch exchange positions;
- look up terminal state for local open live orders by `client_order_id`;
- pass normalized snapshots to `RealTradeImportService.reconcile_connection`.

The sync client must not submit or cancel orders. It only reads exchange state.

`ExchangeOrderSnapshot` is the normalized order contract consumed by
reconciliation:

- `exchange`, `symbol`
- `exchange_order_id | None`
- `client_order_id | None`
- `side`: `buy` or `sell`
- `order_type | None`: `market`, `limit`, `stop`, or `take_profit`
- `status`: normalized exchange status such as `submitted`,
  `partially_filled`, `filled`, `cancelled`, or `rejected`
- `quantity | None`
- `filled_quantity | None`
- `price | None`, `stop_price | None`, `avg_price | None`
- `reduce_only`
- optional `role`: `entry`, `protective_stop`, or `take_profit`
- optional `signal_id`, `position_id`
- optional `updated_at`
- `raw`

`ExchangePositionSnapshot` is the normalized position contract:

- `exchange`, `symbol`
- `side`: `long` or `short`
- `quantity`
- `entry_avg_price`
- optional `signal_id`, `position_id`, `exchange_position_id`
- optional `mark_price`, `unrealized_pnl`, `updated_at`
- `raw`

Idempotency is based on available identity fields in this order:

- `client_order_id`
- `exchange_order_id`
- `signal_id`
- `position_id`

Reconciliation behavior:

- partial entry fills update local order status and local live position
  quantity/entry price to the exchange-reported actual position;
- cancelled or rejected entry orders close any unmatched local live position so
  it no longer contributes to real open risk;
- filled reduce-only stop/TP orders close the matched local live position when
  the exchange no longer reports an open position;
- exchange position size mismatches update local live position quantity;
- local live positions missing from exchange positions are closed and audited;
- unmatched exchange positions are audited as manual/external positions and are
  not silently inserted as local strategy positions.

`external_exchange_orders` remains idempotent by
`connection_id + exchange_order_id`; client order ids, reduce-only flags,
filled quantities, and local identity fields are stored in order metadata for
backward compatibility.

Real risk state continues to read open live risk from local `positions`, but
after reconciliation those positions reflect actual exchange positions rather
than only local execution intent.

## L2 Orderbook Market Quality v1

`OrderbookSnapshotWorker` refreshes configured/watchlist Bybit symbols and
writes normalized hot L2 snapshots to Redis key
`orderbook:{exchange}:{symbol}`.

`OrderBookSnapshot` fields:

- `exchange`, `symbol`, `category`
- `bids`, `asks`: normalized levels with `price` and `quantity`
- `timestamp`: source/fetch timestamp in milliseconds
- `ts`: ISO-8601 UTC timestamp for compatibility with existing hot payloads
- `source`: `bybit_v5_orderbook` for real L2 snapshots
- `spread_bps`
- `bid_depth_usd_0_1_pct`, `ask_depth_usd_0_1_pct`
- `bid_depth_usd_0_5_pct`, `ask_depth_usd_0_5_pct`
- `bid_depth_usd_1_pct`, `ask_depth_usd_1_pct`

Depth bands are measured from the best bid/ask. Bids include levels at or
above `best_bid * (1 - band)`; asks include levels at or below
`best_ask * (1 + band)`.

`RiskMarketDataService` reads the Redis L2 snapshot for Bybit market context.
It exposes `spread_bps`, entry-side `orderbook_depth_usd` from the 0.5% band,
and `market_data_status`:

- `fresh`: a non-placeholder L2 snapshot is present and within the configured
  orderbook snapshot max age
- `stale`: a real L2 snapshot exists but is older than the configured max age
- `missing`: no usable L2 snapshot exists, including legacy
  `orderbook_l2_not_available` placeholder payloads

`RiskManagementSettings` adds:

- `real_requires_fresh_market_data: bool = True`

When `real_requires_fresh_market_data` is enabled, real entries are blocked for
`missing` or `stale` market data. Virtual entries warn instead. If disabled,
real entries also warn, while other risk checks still apply.

## No-Trade Filters v1

`StrategySignal` and `RadarSignal` expose optional
`no_trade_filter: NoTradeFilterResult | None`. The no-trade layer is evaluated
after strategy setup, market quality, regime, confirmation, and RR checks. It
does not change strategy formulas; it converts hard entry blockers into an
explicit signal layer.

`NoTradeFilterResult` fields:

- `enabled`
- `blocked`
- `hard_block`
- `blockers`
- `warnings`
- `checks: list[SignalLayerCheck]`
- `metadata`

The no-trade check names are:

- `near_htf_obstacle`
- `low_liquidity`
- `high_spread`
- `high_slippage`
- `overextended_entry`
- `extreme_funding`
- `strategy_cooldown`
- `daily_loss_streak`
- `negative_edge`
- `missing_market_data`

Hard no-trade results must be visible in `signal.risks`, persisted in
`features_snapshot.no_trade_filter`, and surfaced as a `no_trade_filter`
confirmation check. A hard no-trade result makes the signal non-actionable,
sets disabled `auto_entry` metadata, and prevents lifecycle promotion to
`actionable`.

`RiskContext` carries `no_trade_filter`. RiskGate blocks real and virtual
trade confirmation when `no_trade_filter.blocked` is true. Research-only
warning behavior is not introduced in v1.

No-trade settings are configurable through strategy runtime/risk settings:

- `no_trade_filters_enabled`
- `max_spread_bps_for_entry`
- `max_slippage_bps_for_entry`
- `min_depth_usd_for_entry`
- `max_obstacle_distance_r`
- `cooldown_after_stop_minutes`
- `max_strategy_losses_per_day`

Existing related settings remain honored where applicable:
`real_requires_fresh_market_data`, `real_requires_positive_edge`,
`edge_min_sample_size`, `min_expectancy_after_costs_r`, and strategy funding
thresholds such as `funding_block_threshold`.

---

# Rules

## run_strategies
- pure function
- no DB
- no external APIs

## calculate_features
- must use only market data
- no external calls

## execution
- must use config
- no hardcoded values

## RiskManagementSettings
- `strategy_risk_multipliers` must include current strategy keys:
  `trend_pullback_continuation`, `volatility_squeeze_breakout`,
  `liquidity_sweep_reversal`.
- Legacy strategy aliases remain supported:
  `trend_following`, `breakout`, `smart_money_setup`.
- Strategy multiplier lookup uses exact normalized strategy key first,
  then legacy alias fallback, then `1.0`.

## Strategy RR eligibility
- `risk_reward_guard` failed checks make the signal non-actionable for real
  and virtual entries.
- Failed RR snapshots expose `metadata.risk_reward_blocked = true` and
  `metadata.risk_reward_block_reason`.
- Failed RR signals expose disabled `auto_entry` metadata so auto-entry cannot
  be armed by pipeline output.
