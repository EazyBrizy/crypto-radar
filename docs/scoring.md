# Signal Scoring

Runtime scoring uses a 0-100 scale.

The shared score is the positive layer total minus penalties:

```text
trend_score
+ volume_score
+ liquidity_score
+ orderbook_score
+ risk_reward_score
+ volatility_score
- overheat_penalty
- news_event_risk_penalty
```

Rules:

- `70+`: actionable candidate if shared quality, regime, confirmation, and RR
  guards pass.
- `60-69`: visible watchlist/ready setup.
- `<60`: usually hidden unless a strategy has a lower visible setup threshold.

## Heuristic Score Vs EV

The 0-100 score is a heuristic quality score. It ranks how well the current
setup matches the strategy model, market regime, confirmations, liquidity, and
RR quality. It is useful for sorting, UI explanation, watchlist state, and
pipeline gating.

Expected value is a separate calibration layer. The EV gate reads historical
and forward outcomes from strategy performance analytics and produces a
`SignalEdgeSnapshot`. EV must not rewrite the heuristic `score`; it answers a
different question: whether similar signals have enough evidence of positive
expectancy after costs.

Real entries require both layers:

- heuristic score high enough for the pipeline and strategy status;
- RR guard passed;
- no hard no-trade filter;
- positive edge after costs;
- enough edge sample size;
- fresh market data and valid execution context.

Virtual research may continue with unknown or insufficient edge warnings, but
real execution must not.

## Edge Snapshot

`SignalEdgeSnapshot` is the per-signal EV summary attached to
`StrategySignal.edge` and `RadarSignal.edge`.

Fields:

- `status`: `unknown`, `positive`, `negative`, or `insufficient_sample`;
- `sample_size` and `min_sample_size`;
- `winrate`;
- `avg_win_r` and `avg_loss_r`;
- `expectancy_r`;
- `expectancy_after_costs_r`;
- `profit_factor`;
- `confidence_score`;
- `source`: `outcome`, `backtest`, `mixed`, or `none`;
- `score_bucket`;
- `metadata`.

`expectancy_after_costs_r` is the value consumed by the real EV gate. Missing
cost conversion should be explicit in metadata rather than silently treated as a
production-quality estimate.

## Score Buckets

Strategy performance aggregation groups signals into score buckets:

- `0-49`
- `50-59`
- `60-69`
- `70-79`
- `80-89`
- `90-100`

The EV lookup should prefer the most specific available profile:
strategy/exchange/symbol/timeframe/regime/score bucket first, then broader
fallbacks when the exact sample is insufficient.

## Real Entry Requirements

A real entry is eligible only when:

- the signal is actionable after shared pipeline checks;
- RR passed against the selected `TradePlan` target;
- `no_trade_filter.blocked` is false;
- edge exists and is positive;
- edge sample size meets `edge_min_sample_size`;
- `expectancy_after_costs_r > min_expectancy_after_costs_r`;
- market data is fresh;
- orderbook spread/depth/slippage checks pass;
- exchange rules are fresh and valid;
- futures liquidation buffer is valid when trading futures;
- protective orders are available in the execution plan.

These requirements are business rules in services/risk gates, not strategy
formulas and not frontend-only checks.

## Volatility Squeeze Breakout

Target score budget is 100 max.

Compression:

- `+20` BB width percentile below the configured threshold, default `20`.
- `+15` ATR14 below ATR SMA50.
- `+10` current Donchian/range_20 below recent average.

Breakout:

- `+20` candle closes outside Donchian range.
- `+15` volume spike above configured multiplier, default `1.5x`.
- `+10` close is in the directional part of the candle, default `0.7`.
- `+10` ATR is expanding.

Context:

- Higher timeframe alignment is added by the shared regime layer:
  aligned context adds score; strong conflict applies a penalty or downgrades
  status.

Penalty:

- `-20` wick-only break closes back inside the range.
- `-15` breakout candle body above `2.5 ATR`.
- `-15` rejection wick above the configured maximum, default `0.35`.
- RR, spread/liquidity, and higher-timeframe S/R penalties are applied by
  shared pipeline layers, not duplicated inside the strategy.

## Liquidity Sweep Reversal

Target score budget is 100 max.

Level quality:

- `+20` visible 20-50 candle fractal swing high/low exists.
- `+10` level has at least two recent touches/equal-high or equal-low behavior.
- `+5` volume around the level is above local average.
- `+10` higher-timeframe S/R confluence is added by the shared regime layer.

Sweep:

- `+20` price sweeps the level; the same score is kept for unreclaimed READY
  states, then penalized if close remains beyond the level.
- `+15` directional wick ratio is above the configured threshold, default
  `0.45`.
- `+10` sweep volume is above the configured multiplier, default `1.3x`.

Confirmation:

- `+10` next candle confirms the reversal through the sweep candle's micro
  structure.
- `+10` current candle closes through previous-candle micro structure in the
  reversal direction.

Context and penalties:

- `+5` local ADX/trend context is not strongly against the reversal.
- `-25` close settles beyond the swept level.
- `-20` next candle continues the breakout.
- `-20` setup is against a strong local trend.
- RR, spread/liquidity, and low-liquidity penalties stay in shared pipeline
  layers.
