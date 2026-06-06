# Prompt 6 Forward Virtual Strategy Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated forward virtual strategy-test runs with live counters, cancel/status API, worker ownership, and frontend Backtest/Forward affordances.

**Architecture:** Extend the existing strategy-testing schemas/store/service/API and ClickHouse analytics path. Add a focused forward runner state machine plus a polling worker; keep historical backtests on the current background-task path.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, Pydantic, ClickHouse analytics store, unittest, React/Next, TanStack Query, Vitest.

---

## Tasks

- [x] Add backend RED tests for `test_type`, statuses, persisted summary/runtime_state, status API, cancel API, and forward enqueue.
- [x] Add backend RED tests for forward runner signal rows, no radar writes, virtual auto-entry, pending expiry, stop close, and summary counters.
- [x] Add frontend RED tests for Backtest/Forward tabs, forward payload, runs-table counters/cancel, live dashboard, and API paths.
- [x] Extend backend schemas and TS types with `StrategyTestType`, `stopping`/`cancelled`, and live summary fields.
- [x] Add Alembic migration and SQLAlchemy model/store support for `test_type`, persisted `summary`, `runtime_state`, and `last_heartbeat_at`.
- [x] Add run-store methods for summary/runtime_state updates, cancellation, status lookup, and queued/running forward-run polling.
- [x] Route historical runs through the existing background task and forward runs through worker-owned enqueue only.
- [x] Implement `StrategyForwardTestRunner` with injectable providers, isolated pending/position/account state, signal/trade row output, and minimal safe restart behavior.
- [x] Add `strategy_forward_test_worker.py` and wire it into FastAPI lifespan with start/stop.
- [x] Add status/cancel API endpoints and service methods.
- [x] Update frontend API hooks and query keys for status/cancel/signals polling.
- [x] Update Strategy Testing UI tabs, request construction, runs table, and live report dashboard.
- [x] Run focused backend tests, focused frontend tests, frontend typecheck, and diff checks.
- [x] Commit with `feat: add forward virtual strategy tests`.
