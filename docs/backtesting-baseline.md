# LAB-02 Strategy Baseline

LAB-02 adds a reproducible baseline harness for the current strategy set before
AUD-02..AUD-10 change strategy behavior, fallback handling, candle boundaries,
pipeline decisions, or exits.

Run:

```powershell
python scripts/run_strategy_baseline.py `
  --symbols BTCUSDT `
  --timeframes 1h `
  --start-time 2026-01-01T00:00:00Z `
  --end-time 2026-02-01T00:00:00Z `
  --output-path .codex-dev-logs/strategy-baseline.json
```

Baseline strategies:

- `liquidity_sweep_reversal`
- `volatility_squeeze_breakout`
- `trend_pullback_continuation`

The output is JSON with one summary row per strategy/symbol/timeframe. Each row
includes `baseline_id`, `run_id`, `source=baseline`, `baseline_version`,
`strategy`, `symbol`, `timeframe`, `candle_state=closed`, `created_at`, and
`code_revision` when git can provide it.

No historical dataset is bundled with the harness. If ClickHouse has no closed
candles for the requested matrix, the scenario status must be `no_data`. If
there are too few closed candles for warmup and simulation, the status must be
`insufficient_data`. Metrics are valid only for scenarios with real historical
samples; missing metrics stay `null` and must not be replaced with fabricated
zeros.

Use this JSON as the comparison point for later AUD-02..AUD-10 patches. New
experiments should keep their own `source=experiment` or Strategy Lab
experiment tags and compare against the saved LAB-02 baseline artifact.
