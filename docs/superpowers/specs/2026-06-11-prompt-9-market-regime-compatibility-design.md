# Prompt 9 Market Regime Compatibility Design

## Goal

Strategies should only become execution candidates when the current market regime is compatible with the strategy and direction. The existing `direction` / `strength` / `alignment` fields stay available, but `MarketRegimeSnapshot` gains richer regime, volatility, structure, and compatibility metadata.

## Backend Design

`MarketRegimeFilter` remains the single place that classifies market context. It will derive:

- `regime_type`: `trend_up`, `trend_down`, `range`, `chop`, `volatility_compression`, `volatility_expansion`, `post_impulse`, `liquidity_sweep_zone`, or `unknown`.
- `volatility_state`: `compression`, `normal`, `expansion`, or `unknown`.
- `structure_state`: `trend`, `range`, `chop`, or `unknown`.
- `compatibility`: a dict with `status`, `reason`, `reason_code`, `strategy`, `direction`, and the evidence used by the matrix.

Classification uses existing `Features` fields only: EMA/VWAP/swing structure for trend, EMA200 chop and low separation for chop, `bb_width_percentile` and `range_20_atr` for compression, candle body/range ATR for expansion and post-impulse, Donchian/range metrics for range, and repeated swing high/low touches near price as the liquidity-sweep-zone proxy.

## Compatibility Matrix

`trend_pullback_continuation` passes for `trend_up` long and `trend_down` short. It fails in `chop`, fails or warns in `range` unless `allow_range_pullback=true`, and fails against a strong higher-timeframe trend.

`liquidity_sweep_reversal` passes in `range` and `liquidity_sweep_zone`. Against a strong trend it requires absorption and reclaim evidence from trigger/trade-plan metadata; otherwise it warns or fails.

`volatility_squeeze_breakout` passes only when compression is present before the breakout. In `post_impulse`, it warns and should wait for a retest/pullback unless retest evidence is present.

The compatibility result is emitted as `SignalLayerCheck(name="strategy_regime_compatibility")` on `MarketRegimeSnapshot.checks`.

## Status And Gate

`SignalStatusResolver` treats failed compatibility as non-actionable before trigger checks. It returns a watchlist/ready-style status with `actionability_block_reason="strategy_regime_incompatible"`.

`SignalExecutionGateService` reads the regime compatibility check from `signal.regime`. Failed compatibility becomes a blocker reason with code `strategy_regime_incompatible`; warning compatibility becomes a warning reason. This makes the regime blocker visible to details/card views through the existing `execution_gate.reasons` path.

## UI

`SignalDetails` gets a compact Market Regime block near Trigger and Execution Evidence. It displays `regime_type`, `volatility_state`, `structure_state`, compatibility status, and the compatibility reason. When execution is blocked by regime compatibility, the existing details-view blocker ordering makes it a primary blocker.

Frontend contracts are extended in `types.ts` and `validation/common-schemas.ts` while accepting older payloads by defaulting missing new fields to `unknown` / `{}`.

## Testing

Backend tests cover:

- trend pullback blocked in chop;
- liquidity sweep against strong trend requiring absorption;
- breakout requiring compression;
- regime blocker reaching execution gate.

Frontend tests cover:

- `SignalDetails` rendering the market regime block and compatibility reason;
- schema/type normalization accepting the new regime fields.

## Notes

Analytics helpers should prefer `regime_type` when it is not `unknown`, and fall back to the legacy `direction:strength:alignment` key for older snapshots.
