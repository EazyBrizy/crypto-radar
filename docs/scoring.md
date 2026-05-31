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
