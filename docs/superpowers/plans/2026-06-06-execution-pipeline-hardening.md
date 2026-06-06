# Execution Pipeline Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Crypto Radar execution-ready signals, notifications, entry actions, deduplication, trigger confirmation, edge gates, and pending-entry outcomes match the approved execution pipeline hardening design.

**Architecture:** Harden the existing backend service boundaries instead of rewriting the scanner. `SignalExecutionGateSnapshot` becomes the canonical execution contract, write-side dedup runs before publish/notification, trigger and eligibility snapshots become optional API fields, and frontend renders backend-provided blockers without doing trading math.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, pytest, Next.js, React, TypeScript, Vitest, pnpm, Redis/Postgres-compatible service boundaries.

---

## File Structure

- Modify `backend/app/core/config.py` for execution, dedup, edge, and validation settings.
- Modify `backend/app/schemas/signal.py` for `SignalTriggerSnapshot` and optional trigger fields.
- Modify `backend/app/services/signal_execution_gate.py` for settings-driven gate rules.
- Modify `backend/app/services/signal_status_resolver.py` for trigger and strict open-candle status rules.
- Modify `backend/app/strategies/pipeline.py` for trigger snapshot construction and pipeline comments/checks.
- Modify `backend/app/strategies/engine.py` only if gate recalculation needs eligibility metadata after edge attachment.
- Create `backend/app/services/signal_deduplication.py` for rank and keep/suppress/replace decisions.
- Modify `backend/app/repositories/signal_repository.py` for market-direction listing and dedup snapshot/status transitions.
- Modify `backend/app/services/signal_service.py` only to expose repository methods needed by worker dedup.
- Modify `backend/app/workers/signal_worker.py` for dedup and notification source-of-truth.
- Modify `backend/app/services/notification_service.py` for `signal.execution_ready` payload and dedup lookup.
- Modify `backend/app/services/pending_entry_trigger.py`, `backend/app/services/pending_entry.py`, `backend/app/repositories/pending_entry_repository.py`, and `backend/app/services/signal_outcome_service.py` for reason-code propagation and no-entry outcomes.
- Modify `backend/app/services/strategy_performance_service.py` and `backend/app/services/edge_calibration.py` for no-entry/entry-touch metrics where existing models allow it.
- Create `backend/app/services/execution_strategy_registry.py` for walk-forward/outcome eligibility.
- Create `scripts/calibrate_execution_gate.py` as a CLI shell around existing strategy testing/backtest services.
- Modify frontend files: `frontend/src/types.ts`, `frontend/src/domain/signal-status.ts`, `frontend/src/components/SignalCard.tsx`, `frontend/src/components/SignalDetails.tsx`, `frontend/src/features/app-shell/RadarPage.tsx`, `frontend/src/features/app-shell/NotificationRuntime.tsx`, `frontend/src/features/app-shell/NotificationCenter.tsx`, and `frontend/src/i18n/dictionary.ts`.
- Update docs: `docs/BACKEND.md`, `docs/FRONTEND.md`, `docs/PROJECT_STRUCTURE.md`, create `docs/STRATEGIES.md`, create `docs/WORKERS.md`.

## Task 1: Settings, Gate Thresholds, And Notification Source Of Truth

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/signal_execution_gate.py`
- Modify: `backend/app/workers/signal_worker.py`
- Modify: `backend/app/services/notification_service.py`
- Test: `backend/tests/test_signal_execution_gate.py`
- Test: `backend/tests/test_signal_worker_notifications.py`
- Test: `backend/tests/test_notification_service_contract.py`

- [ ] **Step 1: Write failing settings/gate tests**

Add tests asserting:

```python
def test_open_candle_is_blocked_when_closed_candle_only_is_enabled():
    gate = SignalExecutionGateService().evaluate(_signal(candle_state="open"))
    assert gate.feed_kind == "blocked"
    assert not gate.can_notify
    assert not gate.can_enter_now
    assert not gate.can_arm_pending
    assert "forming_candle" in _reason_codes(gate)

def test_positive_edge_below_expectancy_threshold_blocks_execution():
    signal = _signal(edge=_edge("positive", sample_size=80, expectancy=0.01))
    gate = SignalExecutionGateService().evaluate(signal)
    assert gate.feed_kind == "blocked"
    assert "edge_expectancy_below_threshold" in _reason_codes(gate)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/test_signal_execution_gate.py -q
```

Expected: the new expectancy-threshold test fails before implementation because the current gate accepts all positive edge snapshots.

- [ ] **Step 3: Add settings fields**

Add the fields from the approved design to `Settings` in `backend/app/core/config.py`.

- [ ] **Step 4: Make gate settings-driven**

Update `SignalExecutionGateService.evaluate()` to default `execution_score_threshold` from `settings.execution_min_score`, block open candles whenever `settings.execution_closed_candle_only` is true, and make `_edge_reason()` check expectancy, profit factor, entry touch rate, and no-entry rate metadata.

- [ ] **Step 5: Tighten notification gate**

Update `_should_notify_signal()` in `backend/app/workers/signal_worker.py` to require `feed_kind == "execution_signal"` when an execution gate exists. Legacy fallback must require execution-candidate status, closed candle, and score at least `settings.execution_min_score`.

- [ ] **Step 6: Update notification payload**

Change `NotificationService.create_signal_notification()` to emit type `signal.execution_ready`, title `Execution signal`, and payload fields for `feed_kind`, `execution_gate`, `edge`, `selected_rr`, and `status_reason`.

- [ ] **Step 7: Verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_signal_execution_gate.py backend/tests/test_signal_worker_notifications.py backend/tests/test_notification_service_contract.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/core/config.py backend/app/services/signal_execution_gate.py backend/app/workers/signal_worker.py backend/app/services/notification_service.py backend/tests/test_signal_execution_gate.py backend/tests/test_signal_worker_notifications.py backend/tests/test_notification_service_contract.py
git commit -m "feat: harden execution gate notifications"
```

## Task 2: Open-Candle Scanner Contract

**Files:**
- Modify: `backend/app/services/market_scanner.py`
- Modify: `backend/app/services/signal_status_resolver.py`
- Test: `backend/tests/test_strategy_signal_pipeline.py`
- Test: `backend/tests/test_signal_status_contract.py`
- Test: `backend/tests/test_signal_worker_notifications.py`

- [ ] **Step 1: Write failing tests**

Add or extend tests proving:

```python
def test_status_resolver_blocks_forming_candle_execution_gate():
    decision = SignalStatusResolver().resolve(..., candle_state="open", ...)
    assert decision.status == "watchlist"
    assert decision.actionability_block_reason == "forming_candle"

def test_signal_worker_does_not_notify_open_candle():
    assert not _should_notify_signal(_signal(candle_state="open", execution_gate=_blocked_gate("forming_candle")))
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/test_strategy_signal_pipeline.py::StrategySignalPipelineTest::test_status_resolver_blocks_forming_candle backend/tests/test_signal_worker_notifications.py -q
```

Expected: at least one new assertion fails if gate/status metadata is incomplete.

- [ ] **Step 3: Implement scanner helper**

Add `_is_open_candle(candle)` or use `candle.is_closed` consistently. If previews are disabled, skip open candles before feature processing generates strategy signals.

- [ ] **Step 4: Preserve preview path**

When previews are enabled, let open-candle features produce watchlist/market-idea signals only and ensure the gate contains `forming_candle`.

- [ ] **Step 5: Verify GREEN**

```powershell
python -m pytest backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_status_contract.py backend/tests/test_signal_worker_notifications.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/market_scanner.py backend/app/services/signal_status_resolver.py backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_status_contract.py backend/tests/test_signal_worker_notifications.py
git commit -m "feat: enforce open candle preview contract"
```

## Task 3: Global Signal Deduplication

**Files:**
- Create: `backend/app/services/signal_deduplication.py`
- Modify: `backend/app/repositories/signal_repository.py`
- Modify: `backend/app/services/signal_service.py`
- Modify: `backend/app/workers/signal_worker.py`
- Test: `backend/tests/test_signal_deduplication.py`
- Test: `backend/tests/test_signal_repository_execution_gate.py`
- Test: `backend/tests/test_signal_worker_notifications.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_signal_deduplication.py` with tests for keep, suppress, replace, opposite direction, different symbol, and open-candle-vs-closed ranking.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/test_signal_deduplication.py -q
```

Expected: import error for missing `app.services.signal_deduplication`.

- [ ] **Step 3: Implement dedup service**

Implement `DedupDecision`, `SignalDeduplicationService`, `dedup_key(signal)`, and a deterministic `rank_signal(signal)` tuple matching the approved design.

- [ ] **Step 4: Add repository market-direction listing**

Add `list_open_signals_for_market_direction(exchange, symbol, direction, since)` to the protocol and Postgres implementation. Query open statuses, exchange, normalized symbol, direction, and `detected_at >= since`.

- [ ] **Step 5: Integrate worker**

After upsert, ask the service to compare the candidate with open same-direction signals. Suppressed candidates do not notify. Replaced old signals transition terminal with reason `dedup_replaced_by_better_signal`.

- [ ] **Step 6: Persist dedup metadata**

Store `features_snapshot.dedup` with key, action, reason, suppressed/replaced ids, and rank. Add repository helper methods if direct snapshot updates are needed.

- [ ] **Step 7: Verify GREEN**

```powershell
python -m pytest backend/tests/test_signal_deduplication.py backend/tests/test_signal_repository_execution_gate.py backend/tests/test_signal_worker_notifications.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/signal_deduplication.py backend/app/repositories/signal_repository.py backend/app/services/signal_service.py backend/app/workers/signal_worker.py backend/tests/test_signal_deduplication.py backend/tests/test_signal_repository_execution_gate.py backend/tests/test_signal_worker_notifications.py
git commit -m "feat: dedupe execution signals by market direction"
```

## Task 4: Trigger Snapshot And Status Integration

**Files:**
- Modify: `backend/app/schemas/signal.py`
- Modify: `backend/app/repositories/signal_repository.py`
- Modify: `backend/app/strategies/pipeline.py`
- Modify: `backend/app/services/signal_status_resolver.py`
- Modify: `backend/app/services/signal_execution_gate.py`
- Test: `backend/tests/test_strategy_signal_pipeline.py`
- Test: `backend/tests/test_signal_execution_gate.py`
- Test: `backend/tests/test_signal_repository_execution_gate.py`

- [ ] **Step 1: Write failing schema/gate tests**

Add tests proving `trigger.passed=False` prevents `execution_signal` and persists through repository snapshots.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_execution_gate.py -q
```

Expected: missing trigger model or missing `trigger_not_confirmed` reason.

- [ ] **Step 3: Add `SignalTriggerSnapshot`**

Add the Pydantic model and optional `trigger` field to `StrategySignal` and `RadarSignal`.

- [ ] **Step 4: Persist trigger**

Include trigger in `_snapshot_from_strategy_signal`, `_snapshot_from_signal`, `_record_to_radar_signal`, and snapshot merge paths.

- [ ] **Step 5: Build trigger in pipeline**

Add a `TriggerLayer` that maps existing confirmation/setup metadata into explicit trigger snapshots for the three current strategies.

- [ ] **Step 6: Enforce trigger in resolver and gate**

Resolver cannot return `actionable` when trigger is missing or not passed. Gate adds `trigger_not_confirmed` blocker for execution candidates without a passed trigger.

- [ ] **Step 7: Verify GREEN**

```powershell
python -m pytest backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_execution_gate.py backend/tests/test_signal_repository_execution_gate.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add backend/app/schemas/signal.py backend/app/repositories/signal_repository.py backend/app/strategies/pipeline.py backend/app/services/signal_status_resolver.py backend/app/services/signal_execution_gate.py backend/tests/test_strategy_signal_pipeline.py backend/tests/test_signal_execution_gate.py backend/tests/test_signal_repository_execution_gate.py
git commit -m "feat: require confirmed signal triggers"
```

## Task 5: Edge Metrics And Strategy Eligibility

**Files:**
- Create: `backend/app/services/execution_strategy_registry.py`
- Modify: `backend/app/services/signal_execution_gate.py`
- Modify: `backend/app/services/edge_calibration.py`
- Modify: `backend/app/services/strategy_performance_service.py`
- Create: `scripts/calibrate_execution_gate.py`
- Test: `backend/tests/test_execution_strategy_registry.py`
- Test: `backend/tests/test_signal_execution_gate.py`
- Test: `backend/tests/test_strategy_performance_service.py`

- [ ] **Step 1: Write failing eligibility tests**

Create tests for no-data block, positive walk-forward allow, negative validation block, and gate integration when `execution_require_walk_forward_edge` is true.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/test_execution_strategy_registry.py backend/tests/test_signal_execution_gate.py -q
```

Expected: missing registry import or missing strategy eligibility reason code.

- [ ] **Step 3: Implement eligibility service**

Read existing performance summaries and return `eligible`, `reason`, metrics, and source. Use outcome source when walk-forward records are absent.

- [ ] **Step 4: Extend performance metrics**

Use existing summary/profile structures to expose pending armed, filled, entry touch rate, fill rate, no-entry rate, and execution rejected rate.

- [ ] **Step 5: Integrate gate**

Gate blocks on eligibility only when `execution_require_walk_forward_edge` is true. Otherwise it records warning/info metadata for UI.

- [ ] **Step 6: Add calibration CLI**

Implement an argparse script that accepts the approved CLI parameters and calls existing strategy testing/backtest services. It must separate train and validation windows and print/save grouped metrics.

- [ ] **Step 7: Verify GREEN**

```powershell
python -m pytest backend/tests/test_execution_strategy_registry.py backend/tests/test_signal_execution_gate.py backend/tests/test_strategy_performance_service.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add backend/app/services/execution_strategy_registry.py backend/app/services/signal_execution_gate.py backend/app/services/edge_calibration.py backend/app/services/strategy_performance_service.py scripts/calibrate_execution_gate.py backend/tests/test_execution_strategy_registry.py backend/tests/test_signal_execution_gate.py backend/tests/test_strategy_performance_service.py
git commit -m "feat: gate execution by edge eligibility"
```

## Task 6: Pending Entry Diagnostics And Outcomes

**Files:**
- Modify: `backend/app/services/pending_entry_trigger.py`
- Modify: `backend/app/services/pending_entry.py`
- Modify: `backend/app/repositories/pending_entry_repository.py`
- Modify: `backend/app/schemas/pending_entry.py`
- Modify: `backend/app/services/signal_outcome_service.py`
- Test: `backend/tests/test_pending_entry_trigger_service.py`
- Test: `backend/tests/test_pending_entry_service.py`
- Test: `backend/tests/test_signal_outcome_service.py`
- Test: `backend/tests/test_strategy_performance_service.py`

- [ ] **Step 1: Write failing pending reason tests**

Add tests for pending not touched, expired before touch, virtual execution rejected, temporary failure not closing outcome, and terminal reason code view mapping.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/test_pending_entry_trigger_service.py backend/tests/test_signal_outcome_service.py -q
```

Expected: missing reason-code fields or incorrect outcome result for terminal pending entries.

- [ ] **Step 3: Extend trigger result**

Add `reason_code`, `gate_snapshot`, `current_price`, and `entry_zone_distance_bps` to `PendingEntryTriggerResult`.

- [ ] **Step 4: Store reason code**

Persist reason code into `request_snapshot` during transitions and map it into `PendingEntryIntentRead.view.reason_code`.

- [ ] **Step 5: Record no-entry outcomes**

Update `SignalOutcomeService.record_pending_entry_terminal()` to distinguish expired/cancelled before touch, virtual rejected, and temporary failures.

- [ ] **Step 6: Verify GREEN**

```powershell
python -m pytest backend/tests/test_pending_entry_trigger_service.py backend/tests/test_pending_entry_service.py backend/tests/test_signal_outcome_service.py backend/tests/test_strategy_performance_service.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/pending_entry_trigger.py backend/app/services/pending_entry.py backend/app/repositories/pending_entry_repository.py backend/app/schemas/pending_entry.py backend/app/services/signal_outcome_service.py backend/tests/test_pending_entry_trigger_service.py backend/tests/test_pending_entry_service.py backend/tests/test_signal_outcome_service.py backend/tests/test_strategy_performance_service.py
git commit -m "feat: record pending entry no-entry outcomes"
```

## Task 7: Frontend Rendering Of Backend Blockers

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/domain/signal-status.ts`
- Modify: `frontend/src/components/SignalCard.tsx`
- Modify: `frontend/src/components/SignalDetails.tsx`
- Modify: `frontend/src/features/app-shell/RadarPage.tsx`
- Modify: `frontend/src/features/app-shell/NotificationRuntime.tsx`
- Modify: `frontend/src/features/app-shell/NotificationCenter.tsx`
- Modify: `frontend/src/i18n/dictionary.ts`
- Test: `frontend/src/components/SignalDetails.test.tsx`
- Test: `frontend/src/components/SignalCard.test.tsx`
- Test: `frontend/src/features/app-shell/RadarPage.test.tsx`
- Test: `frontend/src/features/app-shell/NotificationRuntime.test.tsx`
- Test: `frontend/src/domain/signal-status.test.ts`

- [ ] **Step 1: Write failing frontend tests**

Add tests for forming-candle preview text, trigger not confirmed block, legacy `signal.created` as idea, `signal.execution_ready` as execution notification, and pending-entry terminal reason display.

- [ ] **Step 2: Run RED**

```powershell
cd frontend
corepack pnpm test -- SignalCard SignalDetails RadarPage NotificationRuntime signal-status
```

Expected: new assertions fail before UI copy and type updates.

- [ ] **Step 3: Update types and helpers**

Add optional trigger/eligibility/dedup fields and make helper functions read `execution_gate` as source of truth.

- [ ] **Step 4: Update SignalDetails and SignalCard**

Render forming candle badge/text, trigger section, strategy eligibility, dedup reason, and latest terminal pending-entry reason. Do not add frontend trading calculations.

- [ ] **Step 5: Update notifications**

Display `signal.execution_ready` as execution-ready and legacy non-execution `signal.created` as idea.

- [ ] **Step 6: Verify GREEN**

```powershell
cd frontend
corepack pnpm test -- SignalCard SignalDetails RadarPage NotificationRuntime signal-status
corepack pnpm typecheck
```

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/types.ts frontend/src/domain/signal-status.ts frontend/src/components/SignalCard.tsx frontend/src/components/SignalDetails.tsx frontend/src/features/app-shell/RadarPage.tsx frontend/src/features/app-shell/NotificationRuntime.tsx frontend/src/features/app-shell/NotificationCenter.tsx frontend/src/i18n/dictionary.ts frontend/src/components/SignalDetails.test.tsx frontend/src/components/SignalCard.test.tsx frontend/src/features/app-shell/RadarPage.test.tsx frontend/src/features/app-shell/NotificationRuntime.test.tsx frontend/src/domain/signal-status.test.ts
git commit -m "feat: show execution blockers in radar ui"
```

## Task 8: Documentation And Final Integration Verification

**Files:**
- Modify: `docs/BACKEND.md`
- Modify: `docs/FRONTEND.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Create: `docs/STRATEGIES.md`
- Create: `docs/WORKERS.md`
- Test: backend and frontend verification commands from the design spec

- [ ] **Step 1: Update docs**

Document the final execution pipeline, strategies, workers, frontend ownership, and project structure additions.

- [ ] **Step 2: Run backend verification**

```powershell
python -m pytest backend/tests/test_signal_status_contract.py
python -m pytest backend/tests/test_strategy_signal_pipeline.py
python -m pytest backend/tests/test_radar_service.py
python -m pytest backend/tests/test_pending_entry_trigger_service.py
python -m pytest backend/tests/test_signal_outcome_service.py
python -m pytest backend/tests/test_notification_service_contract.py
python -m pytest backend/tests/test_trading_e2e_virtual_flow.py
```

- [ ] **Step 3: Run frontend verification**

```powershell
cd frontend
corepack pnpm typecheck
corepack pnpm test -- SignalCard SignalDetails RadarPage NotificationRuntime signal-status
```

- [ ] **Step 4: Run final git diff audit**

```powershell
git status --short
git diff --stat
```

Confirm changes are limited to planned files and every explicit design requirement is covered by tests, docs, or an explained limitation.

- [ ] **Step 5: Commit docs and verification fixes**

```powershell
git add docs/BACKEND.md docs/FRONTEND.md docs/PROJECT_STRUCTURE.md docs/STRATEGIES.md docs/WORKERS.md
git commit -m "docs: describe execution pipeline hardening"
```

## Self-Review Notes

- Spec coverage: tasks cover settings, open-candle contract, execution gate, global dedup, notification rules, trigger snapshots, edge/eligibility, pending-entry outcomes, frontend rendering, docs, and final verification.
- Type consistency: `SignalTriggerSnapshot`, `SignalExecutionGateSnapshot`, `DedupDecision`, `ExecutionStrategyEligibilityService`, and pending-entry reason-code fields are named consistently with the approved design.
- Scope split: the plan is broad but staged; each task can pass independently and keeps compatibility with existing APIs.
