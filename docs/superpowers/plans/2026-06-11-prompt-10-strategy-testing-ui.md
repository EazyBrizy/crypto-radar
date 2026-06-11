# Prompt 10 Strategy Testing UI Plan

## Goal

Complete the Strategy Testing UI split between Historical Backtest and Forward Test with live status polling, explicit request types, richer run/report surfaces, and focused tests.

## Task 1: RED Tests For Remaining Gaps

- [x] Update `StrategyTestingPanel.test.tsx`
  - Forward tab shows isolated account warning and duration presets.
  - Forward tab hides `discovery` mode.
  - Historical request includes `test_type: "historical_backtest"` and `tags: ["backtest"]`.
  - Forward request includes `test_type: "forward_virtual"` and `tags: ["forward_test"]`.
  - Active forward report uses status query data.

- [x] Update `StrategyTestRunsTable.test.tsx`
  - Table shows test type, signals, trades, and PnL/equity as separate visible values.
  - Running forward tests expose cancel action.

- [x] Update `StrategyTestReport.test.tsx`
  - Running forward tests render `Live report preview`.
  - Live summary includes status, pending, closed trades, PnL, and last tick.
  - Conversion funnel renders Signals, Gate Passed, Pending/Entered, Filled, Closed, Winners, Losers.

- [x] Run RED command:

```powershell
corepack pnpm@10.23.0 --dir frontend test -- StrategyTestingPanel.test.tsx StrategyTestRunsTable.test.tsx StrategyTestReport.test.tsx strategy-tests.api.test.ts
```

Expected: tests fail on the remaining UI gaps.

## Task 2: GREEN Implementation

- [x] Update `StrategyTestingPanel.tsx`
  - Conditional Backtest/Forward settings.
  - Forward duration presets.
  - Forward warning text.
  - Forward mode options limited to `research_virtual` and `production_like`.
  - Same-candle field primary for Backtest, advanced for Forward.
  - Poll `useStrategyTestStatus` for selected active forward run every 2.5s and pass that run to report.

- [x] Update `StrategyTestRunsTable.tsx`
  - Split summary into `Signals`, `Trades`, and `PnL / Equity` columns.
  - Keep cancel button for queued/running/stopping forward runs.

- [x] Update `StrategyTestReport.tsx`
  - Rename live preview heading.
  - Add full live counters and funnel lifecycle summary.

- [x] Update `frontend/src/i18n/dictionary.ts`
  - Add requested EN/RU phrase labels.

- [x] Run GREEN command:

```powershell
corepack pnpm@10.23.0 --dir frontend test -- StrategyTestingPanel.test.tsx StrategyTestRunsTable.test.tsx StrategyTestReport.test.tsx strategy-tests.api.test.ts
```

## Task 3: Verification And Commit

- [x] Run:

```powershell
corepack pnpm@10.23.0 --dir frontend typecheck
git diff --check
```

- [x] Browser verification if in-app Browser and local dev server are available.
- [ ] Commit:

```powershell
git add frontend/src/features/strategy-testing/StrategyTestingPanel.tsx frontend/src/features/strategy-testing/StrategyTestingPanel.test.tsx frontend/src/features/strategy-testing/StrategyTestRunsTable.tsx frontend/src/features/strategy-testing/StrategyTestRunsTable.test.tsx frontend/src/features/strategy-testing/StrategyTestReport.tsx frontend/src/features/strategy-testing/StrategyTestReport.test.tsx frontend/src/i18n/dictionary.ts docs/superpowers/specs/2026-06-11-prompt-10-strategy-testing-ui-design.md docs/superpowers/plans/2026-06-11-prompt-10-strategy-testing-ui.md
git commit -m "feat: polish strategy testing forward UI"
```
