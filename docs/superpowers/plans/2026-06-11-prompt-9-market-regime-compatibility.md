# Prompt 9 Market Regime Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rich market regime classification and strategy compatibility gating so execution signals only appear in compatible regimes.

**Architecture:** Extend `MarketRegimeSnapshot`, classify regime and compatibility in `MarketRegimeFilter`, and let status/gate/UI consume the compatibility check through existing snapshots and reason-code flows.

**Tech Stack:** FastAPI/Pydantic backend, unittest backend tests, Next/React frontend, Vitest frontend tests.

---

## Files

- Modify: `backend/app/schemas/signal.py`
- Modify: `backend/app/strategies/pipeline.py`
- Modify: `backend/app/services/signal_status_resolver.py`
- Modify: `backend/app/services/signal_execution_gate.py`
- Modify: `backend/app/services/edge_calibration.py`
- Modify: `backend/app/services/backtest_runner.py`
- Modify: `backend/tests/test_strategy_signal_pipeline.py`
- Modify: `backend/tests/test_signal_execution_gate.py`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/validation/common-schemas.ts`
- Modify: `frontend/src/components/SignalDetails.tsx`
- Modify: `frontend/src/components/SignalDetails.test.tsx`
- Modify: `docs/STRATEGIES.md`

### Task 1: RED Backend Regime Compatibility Tests

- [x] **Step 1: Add failing backend tests**

Add these tests to `backend/tests/test_strategy_signal_pipeline.py`:

```python
def test_trend_pullback_blocked_in_chop(self) -> None:
    signal = StrategySignalPipeline().finalize(
        _trend_pullback_candidate(_choppy_trend_features()),
        StrategyEvaluationContext(signal_features=_choppy_trend_features(), context_features=_choppy_context_features()),
    )
    self.assertEqual(signal.regime.regime_type, "chop")
    self.assertFalse(signal.regime.compatibility["compatible"])
    self.assertIn("strategy_regime_incompatible", signal.status_reason or "")

def test_liquidity_sweep_against_strong_trend_requires_absorption(self) -> None:
    signal = StrategySignalPipeline().finalize(
        _liquidity_sweep_candidate(_breakout_features()),
        StrategyEvaluationContext(signal_features=_breakout_features(), context_features=_bullish_context_features()),
    )
    self.assertEqual(signal.regime.compatibility["reason_code"], "strategy_regime_incompatible")
    self.assertFalse(signal.regime.compatibility["compatible"])

def test_breakout_requires_compression(self) -> None:
    signal = StrategySignalPipeline().finalize(
        _quality_candidate(_non_compressed_breakout_features()),
        StrategyEvaluationContext(signal_features=_non_compressed_breakout_features(), context_features=_bullish_context_features()),
    )
    self.assertEqual(signal.regime.regime_type, "trend_up")
    self.assertFalse(signal.regime.compatibility["compatible"])
```

Add `test_regime_blocker_reaches_execution_gate` to `backend/tests/test_signal_execution_gate.py` using a signal with a failed `strategy_regime_compatibility` check.

- [x] **Step 2: Run backend RED**

Run:

```powershell
$env:PYTHONPATH='C:\Users\gvenv\Desktop\crypto-radar\backend'; C:\Users\gvenv\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_strategy_signal_pipeline tests.test_signal_execution_gate -v
```

Expected: the new tests fail because `MarketRegimeSnapshot` lacks the new fields and no compatibility check/gate reason exists.

### Task 2: GREEN Backend Schema, Classifier, Status, Gate

- [x] **Step 1: Extend `MarketRegimeSnapshot`**

Add literal fields `regime_type`, `volatility_state`, `structure_state`, and `compatibility` with defaults preserving older payloads.

- [x] **Step 2: Add regime helpers in `pipeline.py`**

Implement small helpers for body/range ATR, volatility state, structure state, regime type, and strategy compatibility. Keep evidence in metadata:

```python
SignalLayerCheck(
    name="strategy_regime_compatibility",
    status="failed" if failed else "warning" if warning else "passed",
    reason=reason,
    metadata={"reason_code": reason_code, "compatible": compatible, "regime_type": regime_type, "strategy": signal.strategy},
)
```

- [x] **Step 3: Wire status resolver**

Before generic actionable promotion, failed compatibility returns non-actionable status and actionability block reason `strategy_regime_incompatible`.

- [x] **Step 4: Wire execution gate**

Read `strategy_regime_compatibility` from `signal.regime.checks`. Failed checks become blocker reasons; warnings become warning reasons.

- [x] **Step 5: Preserve analytics compatibility**

Update edge/backtest regime key helpers to prefer `regime_type` when set and not `unknown`, otherwise return the legacy `direction:strength:alignment`.

- [x] **Step 6: Run backend GREEN**

Run the same backend command as Task 1. Expected: all selected tests pass.

### Task 3: RED/GREEN Frontend Details

- [x] **Step 1: Add failing SignalDetails test**

Add `frontend/src/components/SignalDetails.test.tsx` coverage that renders a signal with:

```ts
regime: {
  signal_timeframe: "15m",
  context_timeframe: "1h",
  direction: "bullish",
  strength: "strong",
  alignment: "against",
  regime_type: "chop",
  volatility_state: "normal",
  structure_state: "chop",
  compatibility: {
    compatible: false,
    status: "failed",
    reason_code: "strategy_regime_incompatible",
    reason: "Trend pullback is blocked in chop."
  },
  score_adjustment: -20,
  checks: []
}
```

Assert that "Market regime", "chop", and the compatibility reason render.

- [x] **Step 2: Run frontend RED**

Run:

```powershell
corepack pnpm --dir frontend test -- SignalDetails.test.tsx
```

Expected: the new test fails because the Market Regime block is not rendered yet.

- [x] **Step 3: Implement frontend contracts and block**

Extend `MarketRegimeSnapshot` in `types.ts`, the Zod regime schema in `validation/common-schemas.ts`, and add `MarketRegimeCompact` to `SignalDetails.tsx`.

- [x] **Step 4: Run frontend GREEN**

Run the same frontend command. Expected: all selected tests pass.

### Task 4: Verification, Docs, Commit

- [x] **Step 1: Update docs**

Update `docs/STRATEGIES.md` with regime types and compatibility matrix behavior.

- [x] **Step 2: Run combined verification**

Run:

```powershell
$env:PYTHONPATH='C:\Users\gvenv\Desktop\crypto-radar\backend'; C:\Users\gvenv\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_strategy_signal_pipeline tests.test_signal_execution_gate tests.test_edge_calibration tests.test_strategy_forward_test_runner -v
corepack pnpm --dir frontend test -- SignalDetails.test.tsx signal-details-view-model.test.ts
corepack pnpm --dir frontend typecheck
git diff --check
```

Expected: all tests/checks pass. Browser verification is attempted if a dev server and in-app Browser are available.

- [ ] **Step 3: Commit Prompt 9**

Stage Prompt 9 files and commit:

```powershell
git add backend/app/schemas/signal.py backend/app/strategies/pipeline.py backend/app/services/signal_status_resolver.py backend/app/services/signal_execution_gate.py backend/app/services/edge_calibration.py backend/app/services/backtest_runner.py backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_execution_gate.py frontend/src/types.ts frontend/src/validation/common-schemas.ts frontend/src/components/SignalDetails.tsx frontend/src/components/SignalDetails.test.tsx docs/STRATEGIES.md docs/superpowers/specs/2026-06-11-prompt-9-market-regime-compatibility-design.md docs/superpowers/plans/2026-06-11-prompt-9-market-regime-compatibility.md
git commit -m "feat: add market regime compatibility gate"
```
