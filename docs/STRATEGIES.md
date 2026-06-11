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

## Trade Plan Contract

Strategy signals must either produce a complete `trade_plan` or provide enough legacy entry/stop/target fields for backend enrichment to build one. A complete execution plan has:

- an entry price or range;
- a structural stop;
- invalidation conditions or a non-fallback invalidation source;
- at least one executable, directional take-profit target;
- risk/reward metadata that still points to an executable target when reporting guards are disabled.

Backtest and strategy-test flows may record explicit legacy assumptions when enriching old signals, but they still pass through the same trade-plan completeness and RiskGate services as production-compatible execution.

## Execution Gate

`SignalExecutionGateService` is the only place that turns a finalized strategy signal into execution permissions. It owns:

- feed kind: `execution_signal`, `watchlist`, `market_idea`, or `blocked`;
- action booleans: notify, enter now, arm pending, show in execution feed;
- blocker and warning reason codes;
- execution score, closed-candle, trigger, risk/reward, edge, eligibility, and trade-plan checks.

Open/forming candles are previews only when previews are enabled. They must not notify or enter while `settings.execution_closed_candle_only` is true.

## Edge And Eligibility

`edge_calibration_service.evaluate_signal_edge()` attaches `SignalEdgeSnapshot` before gate evaluation.

`strategy_execution_eligibility_profiles` is the persisted eligibility source for execution. Completed `historical_backtest` runs aggregate the existing strategy-test metric results by strategy, exchange, symbol scope, timeframe, market regime, score bucket, and direction, then upsert `sample_size`, `expectancy_after_costs_r`, `profit_factor`, `entry_touch_rate`, `no_entry_rate`, `max_drawdown_r`, `run_ids`, `eligible`, and reason fields. The updater consumes the strategy-test metric pipeline; do not add a second metric calculator for eligibility.

`ExecutionStrategyEligibilityService` checks the persisted profile first. It falls back to the attached `SignalEdgeSnapshot` only when no persisted profile exists for that execution key. Persisted profile sources are `historical_backtest`, `forward_virtual`, or `mixed`.

The metadata is advisory by default and becomes a hard blocker only when `settings.execution_require_walk_forward_edge` is enabled.

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
