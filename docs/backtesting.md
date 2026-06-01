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

## No Lookahead

Backtests must use only data known at the decision time.

Rules:

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

## Metrics

Backtest reports keep the existing response shape and should include:

- `trades_count`, `wins`, `losses`, `winrate`;
- `avg_win_r`, `avg_loss_r`, `expectancy_r`, `profit_factor`;
- `max_drawdown_pct`;
- `fees_total`, `slippage_total`, `funding_total`;
- `avg_bars_in_trade`, `mfe_r_avg`, `mae_r_avg`;
- `tp1_rate`, `stop_rate`;
- grouped metrics by strategy, market regime, score bucket, direction, symbol,
  exchange, and timeframe where sample size allows.

Metrics with small samples must be labeled as low confidence. They may inform
research, but they do not satisfy the real EV gate by themselves unless the
configured sample-size threshold is met.

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
