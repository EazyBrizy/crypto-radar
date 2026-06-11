# STRATEGIES

Codex guide for strategy and execution-readiness changes.

## Strategy Modules

`backend/app/strategies/engine.py` currently runs three strategy modules:

- `trend_pullback_continuation`: continuation after trend pullback.
- `volatility_squeeze_breakout`: breakout from compressed volatility.
- `liquidity_sweep_reversal`: reversal after liquidity sweep.

Strategy implementations live in:

- `backend/app/strategies/trend_pullback.py`
- `backend/app/strategies/breakout.py`
- `backend/app/strategies/liquidity_sweep.py`

Shared finalization lives in `backend/app/strategies/pipeline.py`.

## Signal Finalization

The strategy engine produces raw candidates, then `StrategySignalPipeline` finalizes each candidate with:

- market/setup quality layers;
- confirmation and explicit trigger snapshots;
- no-trade filters;
- entry, stop, targets, risk/reward, and invalidation metadata;
- decision metadata used by execution and UI;
- final status and execution gate classification.

Trigger snapshots are required for execution candidates. A missing or failed trigger must block execution through `trigger_not_confirmed`; it should not be patched around in workers or UI.

## Strategy-Specific Triggers

`TriggerLayer` uses strategy-specific trigger checks instead of a generic `confirmation.passed && closed_candle` rule.

- `liquidity_sweep_reversal` requires a closed candle, a swept level, and a reclaim close in the reversal direction. Optional absorption and OI-flush requirements are enforced from strategy params when enabled.
- `volatility_squeeze_breakout` requires prior compression, a closed candle outside the breakout level, and a retest/hold when the setup metadata marks the breakout as large or retest-required.
- `trend_pullback_continuation` requires a closed candle, the configured structural-zone and HTF-alignment requirements, held/reclaimed pullback evidence, and no severe EMA200 chop.

Failed trigger snapshots carry `failed_checks`, `trigger_type`, and strategy evidence in metadata so status resolution, execution gate reasons, and UI diagnostics all explain why a high-score setup is still not actionable.

## Market Regime Compatibility

`MarketRegimeFilter` emits both the legacy direction/strength/alignment fields and a richer regime snapshot:

- `regime_type`: `trend_up`, `trend_down`, `range`, `chop`, `volatility_compression`, `volatility_expansion`, `post_impulse`, `liquidity_sweep_zone`, or `unknown`;
- `volatility_state`: `compression`, `normal`, `expansion`, or `unknown`;
- `structure_state`: `trend`, `range`, `chop`, or `unknown`;
- `compatibility`: backend-only policy evidence surfaced to execution gate and UI.

The compatibility layer writes a `strategy_regime_compatibility` check. Failed compatibility must keep the signal non-actionable and add the `strategy_regime_incompatible` execution-gate blocker.

Strategy matrix:

- `trend_pullback_continuation`: allow `trend_up` longs and `trend_down` shorts; block chop/range unless `allow_range_pullback=true`; block signals against a strong trend.
- `liquidity_sweep_reversal`: prefer range and liquidity-sweep-zone regimes; against a strong trend, require absorption and reclaim evidence.
- `volatility_squeeze_breakout`: require volatility compression before breakout; post-impulse breakouts wait for pullback/retest evidence.

## Execution Gate

`SignalExecutionGateService` is the only place that turns a finalized strategy signal into execution permissions. It owns:

- feed kind: `execution_signal`, `watchlist`, `market_idea`, or `blocked`;
- action booleans: notify, enter now, arm pending, show in execution feed;
- blocker and warning reason codes;
- execution score, closed-candle, trigger, risk/reward, edge, eligibility, and trade-plan checks.

Open/forming candles are previews only when previews are enabled. They must not notify or enter while `settings.execution_closed_candle_only` is true.

## Edge And Eligibility

`edge_calibration_service.evaluate_signal_edge()` attaches `SignalEdgeSnapshot` before gate evaluation.

`ExecutionStrategyEligibilityService` converts edge metrics into eligibility metadata. The metadata is advisory by default and becomes a hard blocker only when `settings.execution_require_walk_forward_edge` is enabled.

The gate checks backend thresholds for:

- sample size;
- expectancy after costs;
- profit factor;
- entry-touch rate;
- no-entry rate;
- validation sample, expectancy, profit factor, and drawdown in strict mode.

Use `scripts/calibrate_execution_gate.py` for train/validation calibration around existing strategy testing and backtest services.

## Deduplication

`SignalDeduplicationService` runs after persistence preparation and before notification. It compares open signals for the same exchange, normalized symbol, and direction.

The rank favors execution-visible, closed-candle, stronger-status, higher-score, positive-edge, better-RR, higher-timeframe signals. Decisions are:

- `keep`: candidate remains active;
- `suppress`: candidate stays non-notifying and records the stronger signal id;
- `replace`: weaker same-direction signals are terminally replaced.

Dedup metadata belongs in backend signal snapshots and is display-only for the frontend.

## Change Rules

- Add backend tests before changing strategy status, trigger, gate, edge, eligibility, or dedup behavior.
- Do not move execution-readiness calculations into route handlers or frontend components.
- Keep strategy-specific logic in strategy modules or pipeline layers; keep cross-strategy execution policy in services.
- Regenerate frontend API types when Pydantic strategy/signal response schemas change.
