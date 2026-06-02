# Backtesting Operating Playbook

Backtests replay closed historical candles through the same service pipeline
used by live signal generation:

```text
Historical candles
-> FeatureEngine
-> StrategyEngine / StrategySignalPipeline
-> TradePlan
-> Pipeline checks
-> RiskGate
-> virtual execution lifecycle simulation
-> outcome metrics
```

Backtests are research tools. They do not grant real execution permission unless
the resulting edge later passes live risk and EV gates with enough sample size.

`ProductionBacktestRunner` is connected as the production service runner for
the legacy backtest surface. It replays closed candles through the service
pipeline and must not use open candle preview data, live scanner preview state,
or any future candle information.

## Backtest Runner vs Strategy Test Lab

`/api/v1/backtests` remains the legacy/single-scenario production-like runner.
It uses `BacktestRunRequest`, `/api/v1/backtests/run`,
`ProductionBacktestRunner`, and `analytics.backtest_results`.

`/api/v1/strategy-lab` is the LAB-01 synchronous Strategy Test Lab surface for
safe batch/matrix research runs on top of `ProductionBacktestRunner.run_detailed`.
It returns the matrix comparison result directly and does not persist orders,
positions, balances, or scanner state.

`/api/v1/strategy-tests` remains the broader persisted Strategy Testing v1 API.
It is a separate measurement and research contour from the legacy backtest
runner. It supports matrix runs by strategy, symbol, timeframe, date range,
parameter set, entry policy, exit policy, fee model, slippage model, and
assumption set. The existing `/backtests` API is not the full Strategy Test Lab.

Strategy Test Lab supports:

- matrix runs by `strategy_code`, `symbol`, `timeframe`, and date range;
- baseline mode, where a request records the reference strategy, parameters,
  costs, tags, and assumptions for later baseline locking;
- experiment mode, where candidate strategy params, entry policies, or exit
  policies are compared against a baseline;
- comparison of entry policies such as aggressive breakout, conservative
  retest, breakout close, limit zone, market entry, and confirmation entry;
- comparison of exit policies such as structural targets, R-multiple targets,
  partial TP, time stop, breakeven, trailing stop, and invalidation exit;
- explicit `no_data` or `insufficient_data` statuses when a scenario cannot
  produce a valid sample.

`research_virtual` disables hard RR/risk execution blocking for research
simulation and reports blocked eligibility reasons and warnings separately.
`production_like` keeps hard gates when configured, including RiskGate behavior
and execution realism checks.
In all modes, failed RR must remain visible as a measured warning or blocked
eligibility reason. It must not silently remove the discovery signal from
research metrics, signal counts, or blocked-candidate reporting.

Backtest and Strategy Test Lab trades are simulated research observations only.
They must not create real execution side effects, submit exchange orders, create
orders or positions, update portfolio balances, or mutate live/virtual
`risk_state`.

## LAB-01 Strategy Lab API

Use `POST /api/v1/strategy-lab/matrix` for batch research runs and
`POST /api/v1/strategy-lab/run` for a single strategy/symbol/timeframe scenario.
Both endpoints accept closed-candle research inputs:

```json
{
  "exchange": "bybit",
  "strategies": ["trend_pullback_continuation"],
  "symbols": ["BTCUSDT"],
  "timeframes": ["1h"],
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-02-01T00:00:00Z",
  "initial_equity": "1000",
  "fees_bps": "10",
  "slippage_bps": "1",
  "max_bars_in_trade": 20,
  "warmup_bars": 200,
  "mode": "baseline",
  "label": "tpullback-reference",
  "tags": {"desk": "research"}
}
```

LAB-01 `mode` is a comparison label:

- `baseline`: reference run used as a stable research comparison point.
- `experiment`: candidate run with changed strategy params, assumptions, or
  tags that can be compared against a baseline.

LAB-01 runs use `research_virtual` runner assumptions internally. They are not
real execution readiness checks and must not call `RealExecutionService`,
exchange adapters, scanner mutation paths, order repositories, position
repositories, portfolio balances, or `risk_state` writers.

Every scenario receives structured tags:

- `source=strategy_lab`
- `mode=baseline|experiment`
- `lab_run_id`
- `strategy`
- `symbol`
- `timeframe`
- `candle_state=closed`

The comparison response groups metrics by strategy, symbol, and timeframe. The
minimum comparison metrics are:

- `total_trades`
- `win_rate`
- `profit_factor`
- `expectancy_r`
- `avg_r`
- `max_drawdown`
- `avg_bars_in_trade`
- `stop_rate`
- `tp1_rate`
- `final_target_rate`
- `fees_paid`
- `slippage_paid`
- `risk_rejections`
- `execution_rejections`
- `fallback_used_count` when fallback metadata is available
- `incomplete_trade_plan_count` when trade-plan completeness metadata is
  available

If the underlying runner reports `no_historical_data`, the scenario status is
`no_data`. If it reports `not_enough_data`, the scenario status is
`insufficient_data`. In both cases Strategy Lab must leave metrics empty rather
than fabricating zero-value baseline or experiment results.

## Backtest Journal Tags

Every backtest or Strategy Test Lab trade projected into the journal must carry
auditable tags or equivalent structured metadata. Required keys:

- `source=backtest`
- `lab_run_id`
- `baseline_id`
- `strategy_code`
- `symbol`
- `timeframe`
- `entry_model`
- `exit_policy`
- `candle_state=closed`
- `fallback_used`
- `fallback_stop_used`
- `fallback_targets_used`
- `target_source`
- `rr_bucket`
- `decision_scope=backtest`
- `sample_batch`
- `fees_model`
- `slippage_model`

Tags must reflect the decision snapshot used for the simulated trade. Baseline
and experiment comparisons must not reuse tags from a different run or scenario.

## No Lookahead

Backtests must use only data known at the decision time.

Rules:

- backtests must evaluate closed candles only;
- open candle previews are live UI/scanner context and must not be used by the
  backtest runner or Strategy Test Lab;
- indicators for candle `N` may use candle `N` only after it is closed;
- an entry generated from candle `N` cannot depend on candle `N + 1`;
- higher-timeframe context must be aligned to the latest closed higher-timeframe
  candle available at that point;
- funding, orderbook, liquidation, and derivative snapshots must be timestamped
  and selected only if they were available at or before the simulated decision.

Any unavailable live-only context must either be omitted with explicit metadata
or simulated conservatively. Silent future-data fills are forbidden.

## Same-Candle Policy

When entry, stop, and target can all be touched inside the same candle, the
backtest must use the configured conservative policy.

Supported policy names:

- `stop_first`: assume stop-loss happens before target;
- `target_first`: assume target happens before stop;
- `ignore_ambiguous`: do not score ambiguous same-candle outcomes as wins.

The default v1 policy is `stop_first`. Reports must expose the chosen policy so
performance comparisons are reproducible.

## Fees, Slippage, And Funding

Backtest PnL must include execution costs whenever the required data is
available:

- entry and exit fees from `fee_rate` or exchange fee assumptions;
- slippage from `slippage_bps` or a configured slippage model;
- funding accrual for futures when funding history or assumptions exist;
- partial-exit fees for TP1/TP2/TP3 lifecycle events;
- conservative fallback costs when exact historical costs are unavailable.

Funding assumptions must state whether they model one interval, full holding
duration, or are unavailable. Results without funding data must not be presented
as production-realistic futures performance.

## Fill Assumptions

Backtests should be conservative:

- market entries fill at the next executable open/bid/ask model, not at an
  impossible mid price;
- limit-zone entries fill only when candle high/low reaches the zone;
- breakout entries require a close beyond the breakout level when the strategy
  says so;
- retest entries fill only if the retest zone is touched after the breakout;
- partial take profits reduce remaining size and keep the rest of the lifecycle
  open;
- protective stops are assumed available for real-style simulations.

If orderbook depth is unavailable, the run must record that liquidity impact is
not fully modeled.

## Signal Selection And Position Limits

Legacy `/api/v1/backtests` runs preserve the old default behavior:
`signal_selection_policy = "first_actionable"` and
`max_concurrent_positions = 1`.

Backtest params may override signal selection and simulated position limits:

- `signal_selection_policy`: `first_actionable`, `highest_score`,
  `all_non_overlapping`, or `all_signals`;
- `max_concurrent_positions`: maximum simultaneous simulated positions;
- `max_positions_per_symbol`: maximum simultaneous positions for one
  `exchange + symbol`, default `1`;
- `cooldown_bars_after_close`: bars that block same
  `exchange + symbol + timeframe + direction` re-entry after close;
- `allow_opposite_signal_flip`: default `false`; when false, opposite
  direction entries for the same `exchange + symbol + timeframe` are blocked
  while a position is open.

`all_non_overlapping` evaluates the signal series while avoiding overlapping
same `exchange + symbol + timeframe + direction` positions. `all_signals`
tries every actionable signal until configured capacity or risk/execution
checks reject further entries. Backtest trades remain simulated research
observations only and must not create orders, positions, portfolio balances, or
live/virtual risk-state mutations.

## Metrics

Backtest reports keep the existing response shape and should include:

- `selected_rr`, `rr_bucket`, `rr_pass_count`, `rr_warning_count`,
  `rr_block_count`;
- `trades_count`, `wins`, `losses`, `winrate`;
- `avg_win_r`, `avg_loss_r`, `expectancy_r`, `profit_factor`;
- `max_drawdown_pct`;
- `fees_total`, `slippage_total`, `funding_total`;
- `avg_bars_in_trade`, `mfe_r_avg`, `mae_r_avg`;
- `tp1_rate`, `tp2_rate`, `stop_rate`, `invalidation_rate`, `expiry_rate`;
- TP/SL outcomes, same-candle policy counts, and close-reason distribution;
- grouped metrics by strategy, market regime, score bucket, direction, symbol,
  exchange, and timeframe where sample size allows.

Metrics with small samples must be labeled as low confidence. They may inform
research, but they do not satisfy the real EV gate by themselves unless the
configured sample-size threshold is met.

Missing data must not be faked. If candles, costs, funding, or a baseline sample
are unavailable, reports must return `no_data` or `insufficient_data` status
metadata for the affected scenario/metric instead of fabricated backtest or
baseline values.

## Limitations

Backtests cannot perfectly reproduce live trading.

Known limitations:

- historical orderbook depth may be missing or lower resolution than live L2;
- exchange rule changes, delistings, and maintenance events may be absent;
- liquidation price and margin-tier behavior may be approximate;
- funding history may not match the user's exchange/account type;
- latency, partial fills, rejected orders, and adapter errors are simplified;
- survivorship bias can appear if symbol universes are not timestamped.

Each run should record assumptions in metadata so later strategy performance and
EV calibration can distinguish high-quality evidence from exploratory tests.
