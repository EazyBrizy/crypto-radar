# Prompt 8 Strategy Specific Triggers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make trigger confirmation strategy-specific so high-score setups are not actionable until the strategy's real trigger is confirmed.

**Architecture:** Keep strategy modules as setup/evidence producers and add trigger dispatch inside `TriggerLayer` in `backend/app/strategies/pipeline.py`. The existing status resolver and execution gate remain the execution policy layer and consume the resulting `SignalTriggerSnapshot`.

**Tech Stack:** FastAPI backend, Pydantic signal schemas, strategy pipeline tests with `unittest`.

---

### Task 1: RED Tests

**Files:**
- Modify: `backend/tests/test_strategy_signal_pipeline.py`
- Modify: `backend/tests/test_signal_execution_gate.py`

- [x] **Step 1: Add failing pipeline tests for liquidity sweep, breakout, trend pullback, and high-score no-trigger behavior.**

Add tests named:

```python
def test_liquidity_sweep_without_reclaim_not_actionable(self) -> None:
    signal = StrategySignalPipeline().finalize(candidate_without_reclaim, context)
    self.assertEqual(signal.trigger.passed, False)
    self.assertEqual(signal.status, "ready")

def test_liquidity_sweep_with_reclaim_trigger_passes(self) -> None:
    signal = StrategySignalPipeline().finalize(candidate_with_reclaim, context)
    self.assertEqual(signal.trigger.passed, True)
    self.assertEqual(signal.trigger.trigger_type, "liquidity_reclaim")

def test_breakout_large_candle_requires_retest(self) -> None:
    signal = StrategySignalPipeline().finalize(large_breakout_candidate, context)
    self.assertEqual(signal.trigger.passed, False)
    self.assertIn("breakout requires retest", signal.trigger.reason)

def test_breakout_retest_trigger_passes(self) -> None:
    signal = StrategySignalPipeline().finalize(retest_candidate, context)
    self.assertEqual(signal.trigger.passed, True)
    self.assertEqual(signal.trigger.trigger_type, "breakout_retest")

def test_trend_pullback_without_structural_zone_not_actionable(self) -> None:
    signal = StrategySignalPipeline().finalize(candidate_without_structural_zone, context)
    self.assertEqual(signal.trigger.passed, False)
    self.assertIn("structural zone", signal.trigger.reason)

def test_score_90_without_trigger_not_execution_signal(self) -> None:
    signal = StrategySignalPipeline().finalize(high_score_without_trigger, context)
    self.assertFalse(signal.execution_gate.can_show_in_execution_feed)
    self.assertIn("trigger_not_confirmed", {reason.code for reason in signal.execution_gate.reasons})
```

Expected RED behavior: at least one test fails because current `TriggerLayer` passes any closed-candle signal whose confirmation passed, even when reclaim/retest/structural-zone trigger evidence is absent.

- [x] **Step 2: Run focused RED tests.**

Run:

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_strategy_signal_pipeline tests.test_signal_execution_gate -v
```

Expected: new Prompt 8 tests fail for missing strategy-specific trigger behavior.

### Task 2: Trigger Dispatch Implementation

**Files:**
- Modify: `backend/app/strategies/pipeline.py`

- [x] **Step 1: Replace generic `TriggerLayer.evaluate()` body with dispatch.**

Dispatch by `signal.strategy`:

```python
if signal.strategy == "liquidity_sweep_reversal":
    return _liquidity_sweep_trigger(signal, context, confirmation)
if signal.strategy == "volatility_squeeze_breakout":
    return _breakout_trigger(signal, context, confirmation)
if signal.strategy == "trend_pullback_continuation":
    return _trend_pullback_trigger(signal, context, confirmation)
return _fallback_current_trigger(signal, context, confirmation)
```

- [x] **Step 2: Add shared trigger snapshot builders.**

Create helpers in `pipeline.py` for:

```python
def _trigger_snapshot(
    signal: StrategySignal,
    context: StrategyEvaluationContext,
    confirmation: SignalConfirmationSnapshot,
    *,
    trigger_type: str,
    passed: bool,
    reason: str,
    check_name: str,
    evidence: dict[str, Any],
    failed_checks: list[str],
) -> SignalTriggerSnapshot:
    check = _trigger_check(
        name=check_name,
        passed=passed,
        reason=reason,
        metadata={
            **evidence,
            "trigger_type": trigger_type,
            "failed_checks": failed_checks,
            "confirmation_passed": confirmation.passed,
            "candle_state": signal.candle_state,
        },
    )
    return SignalTriggerSnapshot(
        trigger_type=trigger_type,
        passed=passed,
        price=_entry_price(signal) or context.signal_features.close,
        candle_state=signal.candle_state,
        confirmed_at=_signal_timestamp_datetime(signal.timestamp) if passed else None,
        reason=reason,
        checks=[check],
        metadata=check.metadata,
    )

def _trigger_check(
    *,
    name: str,
    passed: bool,
    reason: str,
    metadata: dict[str, Any],
) -> SignalLayerCheck:
    return SignalLayerCheck(
        name=name,
        status="passed" if passed else "failed",
        reason=reason,
        metadata=metadata,
    )

def _trigger_failed_checks(evidence: dict[str, Any]) -> list[str]:
    return [key for key, value in evidence.items() if value is False]
```

The metadata must include `trigger_type`, `failed_checks`, `confirmation_passed`, `candle_state`, and strategy-specific evidence.

- [x] **Step 3: Implement liquidity sweep trigger.**

Read existing metadata through `_trade_plan_metadata_*`:

- `swept_level`
- `confirmation`
- `reclaim_score`
- `absorption_score`
- `oi_flush_score`
- `requires_reclaim`

Use `context.signal_features.close` for reclaim direction checks. Return `trigger_type="liquidity_reclaim"` with precise failed reasons.

- [x] **Step 4: Implement breakout trigger.**

Read:

- `range_high`
- `range_low`
- `breakout_closed`
- `large_candle`
- `retest_required`
- `post_breakout_hold_score`
- `retest_quality_score`

Fail large impulse without retest using reason `breakout requires retest`. Pass retest mode when hold/retest score is sufficient.

- [x] **Step 5: Implement trend pullback trigger.**

Read:

- `require_structural_zone`
- `structural_zone_ok`
- `reclaimed_pullback_zone`
- `absorption_confirmed`
- `continuation_score`
- `min_continuation_score`

Also read EMA200 chop from `signal.regime.checks` when available. Fail missing required structural zone with `trigger_not_confirmed`.

### Task 3: Docs And Verification

**Files:**
- Modify: `docs/STRATEGIES.md`
- Modify: `docs/superpowers/plans/2026-06-11-prompt-8-strategy-specific-triggers.md`

- [x] **Step 1: Document strategy-specific trigger rules in `docs/STRATEGIES.md`.**

Add a short section under Signal Finalization that says trigger snapshots are strategy-specific and list the three strategy rules.

- [x] **Step 2: Run focused backend tests.**

Run:

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_strategy_signal_pipeline tests.test_signal_execution_gate -v
```

Expected: all focused tests pass.

- [x] **Step 3: Run broader strategy/gate regression tests.**

Run:

```powershell
..\.venv\Scripts\python.exe -m unittest tests.test_strategy_signal_pipeline tests.test_signal_execution_gate tests.test_strategy_forward_test_runner tests.test_execution_strategy_registry -v
```

Expected: all selected regression tests pass.

- [x] **Step 4: Run `git diff --check`.**

Run:

```powershell
git diff --check
```

Expected: exit code 0, ignoring CRLF conversion warnings.

- [x] **Step 5: Commit Prompt 8.**

Run:

```powershell
git add backend/app/strategies/pipeline.py backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_execution_gate.py docs/STRATEGIES.md docs/superpowers/specs/2026-06-11-prompt-8-strategy-specific-triggers-design.md docs/superpowers/plans/2026-06-11-prompt-8-strategy-specific-triggers.md
git commit -m "feat: add strategy specific trigger layer"
```
