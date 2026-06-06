# Prompt 3 Rejected Status Contract Design

## Goal

Keep `rejected`, `blocked`, and `invalidated` semantically separate across DB, API, repository, radar feeds, and frontend labels.

## Current State

- API/domain already include `rejected`.
- `TradingSignal` DB constraint does not allow `rejected`.
- `SignalRepository` maps `rejected` to `invalidated`.
- `SignalStatusResolver` returns `ready` for `no_trade_filter.blocked`.
- `SignalExecutionGateService` already treats terminal statuses as blocked feed items.
- Frontend marks `rejected` terminal, but fallback labels still collapse it to raw status text or backend card labels.

## Backend Design

DB/model:

- Add Alembic migration `202606060003_add_rejected_signal_status.py`.
- Drop and recreate `ck_trading_signals_status` with:
  `new`, `active`, `watchlist`, `ready`, `actionable`, `wait_for_pullback`,
  `entry_touched`, `confirmed`, `rejected`, `expired`, `invalidated`, `closed`.
- Update `backend/app/models/signal.py` with the same constraint.

Repository:

- `_api_status_to_db("rejected")` returns `rejected`.
- `_strategy_signal_status_to_db("rejected", score)` returns `rejected`.
- `_record_to_radar_signal()` sets `rejected_at` only for `record.status == "rejected"`.
- Existing invalidation paths stay invalidated unless the upstream reason is explicitly a no-trade/dedup rejection.

Resolver/gate:

- `SignalStatusResolver` returns `("rejected", "No-trade hard block: ...")` when `no_trade_filter.blocked`.
- `SignalExecutionGateService` already maps terminal `rejected` to blocked feed; tests lock this.

Radar:

- History mode should include `rejected` through existing terminal status handling.
- Blocked mode should include rejected terminal diagnostics as blocked feed items.

## Frontend Design

- `rejected` remains terminal in `signal-status.ts`.
- `RADAR_STATUS_FILTERS` includes `rejected`.
- Fallback labels:
  - `rejected` card/status badge: `Отклонён`
  - `rejected` details primary label: `Отклонено фильтром` / EN `Rejected by filter`
  - `invalidated`: `Сломано рынком / потеряло актуальность` / EN `Invalidated by market`
- `SignalCard` should not let backend generic card labels collapse rejected into invalidated when `signal.status === "rejected"`.

## Tests

Backend:

- `test_repository_persists_rejected_status`
- `test_signal_status_resolver_no_trade_returns_rejected`
- `test_rejected_status_survives_roundtrip`
- `test_radar_blocked_mode_includes_rejected`

Frontend:

- `signal-status.test.ts` verifies `rejected` terminal and status filters include it.
- `SignalCard.test.tsx` verifies rejected label is distinct from invalidated.

## Acceptance

- No-trade hard block never has status `ready`.
- `rejected` is persisted and returned as `rejected`.
- `invalidated` is reserved for market invalidation or replacement lifecycle, not no-trade rejection.
