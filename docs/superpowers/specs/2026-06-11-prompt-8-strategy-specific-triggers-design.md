# Prompt 8 Strategy Specific Triggers Design

## Goal

Replace the generic trigger rule, `confirmation.passed and candle_state == closed`, with strategy-specific trigger decisions while preserving the current strategy modules and execution gate contracts.

## Current State

`StrategySignalPipeline.finalize()` builds quality, regime, setup, confirmation, trigger, trade plan, status, decision, edge, and execution gate snapshots. `TriggerLayer.evaluate()` currently emits one generic `SignalTriggerSnapshot`. `SignalStatusResolver` already downgrades actionable candidates to `ready` when `trigger.passed` is false, and `SignalExecutionGateService` already blocks execution with `trigger_not_confirmed`.

The three strategy modules already attach the evidence needed by Prompt 8:

- `liquidity_sweep_reversal` stores swept level, reclaim, confirmation, absorption, OI flush, and continuation evidence in trade plan entry/invalidation/metadata.
- `volatility_squeeze_breakout` stores breakout acceptance, retest, large candle, hold score, fakeout, and range evidence in entry/risk metadata.
- `trend_pullback_continuation` stores structural zone, reclaim/absorption, continuation score, HTF target, and EMA200 chop evidence in trade plan metadata and regime checks.

## Recommended Approach

Keep trigger policy inside `backend/app/strategies/pipeline.py` because it is the shared finalization layer that already sees `StrategySignal`, `StrategyEvaluationContext`, `SignalConfirmationSnapshot`, and enriched trade plan metadata. Add strategy-specific dispatch inside `TriggerLayer.evaluate()`:

- `_liquidity_sweep_trigger()`
- `_breakout_trigger()`
- `_trend_pullback_trigger()`
- `_fallback_current_trigger()`

Each helper returns a `SignalTriggerSnapshot` with:

- precise `trigger_type`;
- `passed`;
- user-facing `reason`;
- one primary `SignalLayerCheck` named for the strategy trigger;
- metadata including `trigger_type`, `failed_checks`, `confirmation_passed`, `candle_state`, and the strategy evidence used.

## Strategy Rules

Liquidity sweep:

- Requires closed candle.
- Requires `swept_level`.
- LONG passes only when close is above swept level and reclaim evidence is present.
- SHORT passes only when close is below swept/rejection level and reclaim evidence is present.
- If `require_absorption=true`, absorption score must meet the configured minimum.
- If `require_oi_flush=true`, OI flush must be available and pass.
- Failed trigger uses `trigger_type="liquidity_reclaim"` and reasons such as `Sweep detected but reclaim close is not confirmed`, `Absorption required but missing`, and `OI flush required but unavailable/failed`.

Breakout:

- Requires compression evidence before breakout.
- Requires closed candle outside the breakout level.
- If `large_candle` plus `retest_required`, trigger fails with `breakout requires retest`.
- If `retest_required=true`, trigger type is `breakout_retest` and passes only after retest or hold evidence is present.
- Otherwise trigger type remains `closed_candle` for accepted immediate breakouts.

Trend pullback:

- Requires closed candle.
- If `require_structural_zone=true`, `structural_zone_ok` must be true.
- Requires reclaimed/held structural zone, absorption, or continuation evidence.
- Fails in EMA200 chop.
- Uses `pullback_touch` when the zone is touched/held and `reclaim` when reclaim evidence is present.

## Status And Gate Flow

No new execution policy is added. A failed strategy trigger flows through the existing `SignalStatusResolver` and `SignalExecutionGateService`:

- high-score signals without confirmed trigger become non-actionable with `trigger_not_confirmed`;
- execution gate keeps blocking them;
- gate reason metadata carries the trigger snapshot metadata, including `trigger_type` and `failed_checks`.

## Tests

Backend tests will be added to `backend/tests/test_strategy_signal_pipeline.py` and, where useful, `backend/tests/test_signal_execution_gate.py`:

- `test_liquidity_sweep_without_reclaim_not_actionable`
- `test_liquidity_sweep_with_reclaim_trigger_passes`
- `test_breakout_large_candle_requires_retest`
- `test_breakout_retest_trigger_passes`
- `test_trend_pullback_without_structural_zone_not_actionable`
- `test_score_90_without_trigger_not_execution_signal`

The tests exercise the full pipeline where possible so they prove the integration path, not only private helper behavior.

## Scope

This prompt does not introduce the Prompt 9 regime compatibility matrix. It may read existing regime checks, especially EMA200 chop, but does not expand `MarketRegimeSnapshot`.
