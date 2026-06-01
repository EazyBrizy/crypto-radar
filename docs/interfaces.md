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
