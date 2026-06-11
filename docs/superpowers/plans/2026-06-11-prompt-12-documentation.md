# Prompt 12 Documentation Plan

## Goal

Update project documentation so future agents and operators follow the new radar, execution gate, strategy testing, calibration, worker, and notification architecture.

## Task 1: Documentation Updates

- [x] Update `docs/BACKEND.md`
  - Feed taxonomy: market idea, watchlist, execution signal, blocked diagnostic idea.
  - `execution_gate` as the source of truth.
  - Strategy testing modes and storage.

- [x] Update `docs/frontend.md`
  - UI renders backend eligibility, never recalculates it.
  - Blocked low-score ideas are diagnostics, not trading signals.
  - Strategy testing Backtest/Forward tabs.

- [x] Update `docs/STRATEGIES.md`
  - Strategy-specific triggers.
  - Regime compatibility matrix.
  - Edge calibration flow from strategy tests.

- [x] Update `docs/WORKERS.md`
  - Scanner runner, signal expiry, forward test worker, notification dedup.
  - Forward tests never place real orders.

- [x] Update `README.md`
  - Short operator guide for historical tests, forward tests, calibration, and execution-ready diagnostics.
  - Point future work at `strategy_tests`, not legacy `strategy_lab`.

## Task 2: Verification

- [x] Run `git diff --check`.
- [x] Search docs for required key terms.

## Task 3: Commit

- [x] Commit prompt 12 as a documentation-only change.
