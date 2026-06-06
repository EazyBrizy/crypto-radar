# Prompt 3 Rejected Status Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and display rejected signals distinctly from invalidated signals.

**Architecture:** Update the DB constraint and Alembic migration, stop repository status remapping, make no-trade hard blocks resolve to rejected, and add frontend fallback labels/filters for rejected.

**Tech Stack:** SQLAlchemy/Alembic, Python unittest, React/TypeScript/Vitest.

---

## File Structure

- Create `backend/alembic/versions/202606060003_add_rejected_signal_status.py`.
- Modify `backend/app/models/signal.py`.
- Modify `backend/app/repositories/signal_repository.py`.
- Modify `backend/app/services/signal_status_resolver.py`.
- Modify `backend/app/services/signal_execution_gate.py` only if tests expose missing rejected gate behavior.
- Modify backend tests around repository, resolver, and radar.
- Modify `frontend/src/domain/signal-status.ts` and tests.
- Modify `frontend/src/components/SignalCard.tsx` and tests.

## Tasks

### Task 1: Backend RED Tests

- [ ] Add repository tests proving rejected persists and round-trips as `rejected`.
- [ ] Add resolver test proving `no_trade_filter.blocked` returns `rejected`.
- [ ] Add radar test proving blocked mode includes rejected terminal diagnostics.
- [ ] Run focused backend tests and confirm failures.

### Task 2: Backend GREEN Implementation

- [ ] Add Alembic migration with updated check constraint.
- [ ] Add `rejected` to `TradingSignal` model check constraint.
- [ ] Change repository rejected mappings to return `rejected`.
- [ ] Set `rejected_at` from `record.status == "rejected"`.
- [ ] Change no-trade hard block resolver result to `rejected`.
- [ ] Run focused backend tests green.

### Task 3: Frontend RED Tests

- [ ] Add `signal-status.test.ts` expectations for rejected terminal/filter inclusion.
- [ ] Add `SignalCard.test.tsx` expectation that rejected shows distinct rejected label.
- [ ] Run focused frontend tests and confirm failures where behavior is missing.

### Task 4: Frontend GREEN Implementation

- [ ] Add `rejected` to status filters.
- [ ] Add rejected/invalidated fallback labels and tones.
- [ ] Ensure rejected label wins over generic backend card status labels.
- [ ] Run focused frontend tests and typecheck.

### Task 5: Verification and Commit

- [ ] Run backend focused tests.
- [ ] Run frontend focused tests.
- [ ] Run frontend typecheck.
- [ ] Stage all Prompt 3 files.
- [ ] Commit with `feat: persist rejected signal status`.
