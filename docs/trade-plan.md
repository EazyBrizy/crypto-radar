# Trade Plan Operating Playbook

`TradePlan` is the normalized executable plan between pure strategy output and
the shared risk/execution layers. It exists so the strategy, risk gate, virtual
lifecycle, real adapter, outcome labeling, and backtests all reason about the
same entry, invalidation, targets, and RR assumptions.

## Schema Overview

The plan is attached to `StrategySignal.trade_plan`, mirrored into
`RadarSignal.trade_plan`, and persisted in `features_snapshot.trade_plan` when a
signal is stored.

Core fields:

- `entry`: directional entry model, price or price zone, and optional metadata.
- `stop_loss`: the executable protective stop used for R calculations.
- `targets`: ordered executable targets with price, R multiple, close percent,
  and optional action metadata.
- `invalidation`: conditions that cancel the setup before or after entry.
- `risk_rules`: selected RR target, minimum RR, time stop, breakeven/trailing
  hints, and strategy-specific risk metadata.
- `metadata`: non-executable context such as structure levels, measured move,
  source strategy, and compatibility values.

Legacy signal fields remain available for older clients and analytics:
`entry_min`, `entry_max`, `stop_loss`, `take_profit_1`, `take_profit_2`,
`risk_reward`, `first_target_rr`, `final_target_rr`, `selected_rr`,
`selected_rr_target`, and `min_rr_ratio`.

## Structural vs Fallback Plan

A production-quality trade plan should explain the market idea, not only fill
price fields.

Terms:

- `structural stop`: a protective stop derived from market structure, such as a
  swing low/high, sweep extreme, breakout range boundary, EMA reclaim/loss
  level, or another strategy-specific invalidation level.
- `invalidation thesis`: the condition that proves the setup idea is no longer
  valid before or after entry. It may reference closes, reclaim/acceptance,
  time stops, funding/liquidity filters, or strategy-specific structure.
- `structural target thesis`: the reason for expected profit-taking levels,
  such as range midpoint, opposite range boundary, measured move, liquidity
  pool, higher-timeframe level, or continuation structure.
- `fallback ATR stop`: a synthetic stop created from ATR distance when the
  strategy cannot produce a market-based structural stop.
- `fallback R-multiple targets`: synthetic targets created from the chosen stop
  distance, such as 1R/2R/3R, when the strategy cannot produce structural
  targets.

Fallback is allowed in `research_mode` so discovery, backtests, and Strategy
Test Lab can measure incomplete ideas. Any fallback must be explicit:

- `metadata.fallback_used = true` when any fallback is used;
- `metadata.fallback_stop_used = true` when the stop is ATR/synthetic fallback;
- `metadata.fallback_targets_used = true` when targets are R-multiple fallback;
- `metadata.target_source` should identify `structural`, `r_multiple`,
  `atr_fallback`, `mixed`, or a more specific strategy source.

`production_mode` actionability requires a complete structural trade plan:
entry model, structural stop, invalidation thesis, and structural target thesis.
A fallback plan may remain visible as a research/watchlist/blocked candidate,
but it must not be silently promoted to a production-actionable candidate.

## Entry Types

Supported entry models:

- `market`: use the current executable bid/ask resolved by market context.
- `limit_zone`: enter only inside the strategy entry zone.
- `breakout_close`: enter after a candle closes beyond the breakout level.
- `retest`: wait for a pullback/retest to the broken level or EMA zone.
- `confirmation`: enter only after a follow-up candle confirms direction.

Strategies may expose aggressive and conservative entries in metadata, but the
plan must mark which one is executable. The risk gate evaluates the executable
entry against current market data, price drift, spread, slippage, depth, RR, and
exchange rules.

## Targets

Targets are ordered by execution priority and must be directional:

- long targets must be above entry;
- short targets must be below entry;
- executable targets must have `close_percent > 0`;
- total executable `close_percent` must not exceed `100`;
- each target's `r_multiple` is recalculated from actual entry, stop, and target
  prices by the risk layer.

Typical target usage:

- TP1: partial profit and optional breakeven trigger.
- TP2: main planned exit or trailing activation.
- TP3/runner: optional measured move, range boundary, or trend continuation
  target.

Malformed targets must fail the risk decision. The system must not silently fall
back to risk-settings targets when a signal supplied an invalid `TradePlan`.

## Invalidation

Invalidation is separate from take profit and stop-loss math. It describes when
the setup idea is no longer valid.

Examples:

- pullback loses EMA/structure reclaim;
- breakout closes back inside the compression range;
- sweep level is accepted instead of reclaimed;
- time stop expires before entry or after entry;
- funding, spread, liquidity, or market-data freshness turns into a hard
  no-trade filter.

Outcome labeling uses invalidation metadata to close tracked signals as
`invalidated` or `time_stop` when the candle stream proves the setup expired
without a clean TP/SL outcome.

## Risk Rules

Risk rules are configuration-aware hints, not hardcoded product policy.

The plan may carry:

- `selected_rr_target`: target used by RR checks;
- `min_rr_ratio`: configured minimum RR;
- `time_stop_bars` or time-stop timestamp;
- breakeven activation metadata;
- trailing-stop activation metadata;
- strategy risk notes such as overextension, obstacle distance, funding, or
  open-interest context.

The risk gate is still the authority. It combines the plan with user settings,
account/protection state, exchange rules, market context, no-trade filters, and
edge calibration.

RR in a trade plan is measurement input. Weak RR can mark the plan as
non-executable for a decision scope when the active guard mode is hard, but it
does not delete the underlying discovery signal. The decision snapshot should
record whether the signal remained research-visible, whether
`signal_actionable` was true for the scope, and whether virtual or real
execution was allowed.

## Backward Compatibility

`TradePlan` is additive. Existing clients can continue reading legacy signal
fields, while newer services should prefer `trade_plan` when present.

Compatibility rules:

- keep legacy entry/stop/target/RR fields populated where possible;
- persist the full plan in `features_snapshot.trade_plan`;
- restore the plan to signal response models when it exists;
- use risk-settings-generated take-profit plans only when no `TradePlan` is
  present;
- preserve existing response fields even when the plan adds richer metadata.

No backend or frontend contract should be changed silently. If the plan schema
changes, update `docs/interfaces.md` first and then update the corresponding
tests.
