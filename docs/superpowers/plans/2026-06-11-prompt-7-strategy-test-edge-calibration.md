# Prompt 7 Strategy Test Edge Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish completed strategy-test runs into durable execution eligibility profiles and use them for edge calibration.

**Architecture:** Strategy-test ClickHouse rows remain the analytics source. A new Postgres profile table stores published eligibility decisions keyed by strategy/exchange/symbol/timeframe/regime/score bucket/direction. Edge calibration reads the published profile first, then falls back to existing outcome performance.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, ClickHouse test stores, React, TanStack Query, Vitest.

---

### Task 1: RED Tests

**Files:**
- Create: `backend/tests/test_strategy_test_eligibility_publisher.py`
- Modify: `backend/tests/test_strategy_testing_api_contract.py`
- Modify: `backend/tests/test_strategy_testing_run_store.py`
- Modify: `backend/tests/test_strategy_performance_service.py`
- Modify: `backend/tests/test_edge_calibration.py`
- Modify: `backend/tests/test_signal_execution_gate.py`
- Modify: `frontend/src/api/strategy-tests.api.test.ts`
- Modify: `frontend/src/features/strategy-testing/StrategyTestReport.test.tsx`
- Modify: `frontend/src/components/SignalDetails.test.tsx`

- [x] **Step 1: Write failing tests for publisher, API, edge integration, and UI.**
- [x] **Step 2: Run focused backend and frontend tests and confirm RED failures are due to missing Prompt 7 behavior.**

### Task 2: Backend Implementation

**Files:**
- Modify: `backend/app/models/strategy_testing.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/202606110001_create_strategy_execution_eligibility_profiles.py`
- Create: `backend/app/services/strategy_testing/eligibility_profiles.py`
- Create: `backend/app/services/strategy_testing/eligibility_publisher.py`
- Modify: `backend/app/services/strategy_testing/service.py`
- Modify: `backend/app/api/v1/strategy_tests.py`
- Modify: `backend/app/services/strategy_performance_service.py`
- Modify: `backend/app/services/edge_calibration.py`
- Modify: `backend/app/schemas/strategy_performance.py`
- Modify: `backend/app/schemas/signal.py`

- [x] **Step 1: Add profile model, migration, store, and response schemas.**
- [x] **Step 2: Add publisher aggregation and threshold evaluation.**
- [x] **Step 3: Add service/API publish route.**
- [x] **Step 4: Read published profiles in edge calibration before daily performance.**

### Task 3: Frontend Implementation

**Files:**
- Modify: `frontend/src/features/strategy-testing/types.ts`
- Modify: `frontend/src/api/strategy-tests.api.ts`
- Modify: `frontend/src/features/server-state/query-keys.ts`
- Modify: `frontend/src/features/server-state/use-server-state.ts`
- Modify: `frontend/src/features/strategy-testing/StrategyTestReport.tsx`
- Modify: `frontend/src/features/strategy-testing/StrategyTestingPanel.tsx`
- Modify: `frontend/src/components/SignalDetails.tsx`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/validation/common-schemas.ts`

- [x] **Step 1: Add calibration publish API and mutation.**
- [x] **Step 2: Add report button/result state.**
- [x] **Step 3: Render edge profile source/run ids in SignalDetails.**

### Task 4: Verification And Commit

- [x] **Step 1: Run focused backend tests.**
- [x] **Step 2: Run focused frontend tests.**
- [x] **Step 3: Run frontend typecheck and diff check.**
- [x] **Step 4: Commit Prompt 7 as `feat: publish strategy test calibration profiles`.**
