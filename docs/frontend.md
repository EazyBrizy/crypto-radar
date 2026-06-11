# FRONTEND

Codex guide for the current Next.js frontend. The frontend displays backend state and sends user intents; it does not own trading calculations.

## Stack

- Next.js App Router: `frontend/src/app/`
- React and TypeScript
- Package manager: pnpm through Corepack
- Server state: TanStack Query in `frontend/src/features/server-state/`
- Local UI state: Zustand stores in `frontend/src/stores/`
- API client: `openapi-fetch` in `frontend/src/api/client.ts`
- OpenAPI generated types: `frontend/src/api/generated/`
- Realtime: WebSocket with SSE fallback in `frontend/src/features/realtime/` and `frontend/src/realtime/`
- i18n: `frontend/src/i18n/`
- Styling: global CSS in `frontend/src/app/globals.css` and `frontend/styles/app.css`

## Commands

```powershell
cd frontend
corepack pnpm install
corepack pnpm dev
corepack pnpm test
corepack pnpm lint
```

Regenerate OpenAPI types after backend API/schema changes:

```powershell
cd frontend
corepack pnpm openapi:generate
```

## Runtime Env

- `NEXT_PUBLIC_FASTAPI_HTTP_URL`: FastAPI HTTP origin.
- `NEXT_PUBLIC_FASTAPI_WS_URL`: FastAPI realtime WebSocket URL.
- `NEXT_PUBLIC_FASTAPI_SSE_URL`: FastAPI realtime SSE fallback URL.
- `NEXT_PUBLIC_FASTAPI_TIMEOUT_MS`: frontend request timeout.

## Pages

- Radar: `frontend/src/app/dashboard/radar/page.tsx`, controller in `frontend/src/features/app-shell/RadarRoute.tsx`, view in `frontend/src/features/app-shell/RadarPage.tsx`.
- Watchlist: `frontend/src/app/dashboard/watchlist/page.tsx`, `frontend/src/features/app-shell/WatchlistRoute.tsx`, `frontend/src/features/app-shell/WatchlistPage.tsx`.
- Trades: `frontend/src/app/dashboard/trades/active/page.tsx`, `frontend/src/app/dashboard/trades/journal/page.tsx`, `frontend/src/app/dashboard/trades/analytics/page.tsx`, `frontend/src/features/app-shell/TradesRoute.tsx`, `frontend/src/features/app-shell/TradesPage.tsx`.
- Settings: `frontend/src/app/dashboard/settings/page.tsx`, `frontend/src/features/app-shell/SettingsRoute.tsx`, `frontend/src/features/app-shell/SettingsPage.tsx`.
- Auth and billing: `frontend/src/app/auth/page.tsx`, `frontend/src/app/billing/page.tsx`.

## UI Blocks

- Signal feed: `frontend/src/components/SignalFeed.tsx`, `frontend/src/components/SignalCard.tsx`.
- Signal details and action state: `frontend/src/components/SignalDetails.tsx`, `frontend/src/components/signal-details-view-model.ts`.
- Pending entries queue: `PendingEntriesQueue` inside `frontend/src/features/app-shell/RadarPage.tsx`.
- Strategy testing: `frontend/src/features/strategy-testing/StrategyTestingPanel.tsx`, `StrategyTestRunsTable.tsx`, `StrategyTestReport.tsx`, `StrategyTestMetricGrid.tsx`, and `StrategyTestTradeList.tsx`.
- Exchange connections: settings page plus server-state hooks in `frontend/src/features/server-state/use-server-state.ts`.
- Virtual trades and PnL: `frontend/src/features/app-shell/TradesPage.tsx`, `frontend/src/components/data-table/TradeJournalTable.tsx`, `frontend/src/features/app-shell/ActiveTradeChart.tsx`.
- Charts: `frontend/src/components/charts/`.
- Notifications and realtime status: `frontend/src/features/app-shell/NotificationCenter.tsx`, `frontend/src/features/app-shell/NotificationRuntime.tsx`, `frontend/src/features/app-shell/RealtimeStatusBadge.tsx`.

## API And State Rules

- API wrappers live in `frontend/src/api/`; use them instead of raw fetch in components.
- TanStack Query hooks live in `frontend/src/features/server-state/use-server-state.ts`.
- Query keys live in `frontend/src/features/server-state/query-keys.ts`.
- Realtime events should invalidate or update TanStack Query cache through `frontend/src/realtime/event-router.ts`.
- Zustand is for local UI state only: sidebar, filters, selected ids, realtime UI status.
- Domain enum helpers live in `frontend/src/domain/`.

## Execution Rendering Contract

The Radar UI displays backend execution state. It must not recompute whether a signal is executable.

- Use `signal.execution_gate` as the source of truth for execution feed visibility, action availability, blockers, warnings, and reason codes.
- Use `signal.trigger` only as display context for confirmed or rejected trigger state.
- Use `signal.edge.metadata.strategy_eligibility` only as display context for strategy eligibility.
- Use `signal.execution_gate.metadata.dedup` only as display context for keep/suppress/replace decisions.
- Use pending-entry `view.reason_code` and backend terminal metadata for no-entry, rejected, expired, or temporary-failure outcomes.
- `signal.execution_ready` means the backend approved an execution-ready notification. Legacy `signal.created` is displayed as a non-execution idea unless its payload explicitly says otherwise.
- Signal cards and details should render backend blockers such as `forming_candle`, `trigger_not_confirmed`, `dedup_suppressed_by_better_signal`, strategy eligibility failures, and pending-entry terminal reasons without doing trading math.
- Blocked low-score ideas are diagnostics. In the normal working feed they should be hidden by backend feed policy; in the blocked diagnostics filter they must be labeled as not for execution and should not emphasize entry/TP as a call to trade.
- Disabled action buttons must show backend-provided reasons. Do not render a disabled virtual entry or pending-entry button without a visible caption or tooltip reason.

## Strategy Testing UI

`StrategyTestingPanel` is the canonical frontend for strategy tests. It exposes two explicit tabs:

- Historical backtest: builds `test_type="historical_backtest"` requests with historical start/end dates, mode, same-candle policy, and advanced parameters.
- Forward test: builds `test_type="forward_virtual"` requests with start/end or duration presets, isolated virtual-account warning, and forward-test tags.

The runs table should show test type, status, scenario counts, signals, trades, PnL/equity, created time, report action, and cancel controls for running forward tests. Live forward status is polled from `/api/v1/strategy-tests/runs/{run_id}/status` and rendered as a compact dashboard; it must not inject every forward-test signal into the main radar feed.

Use `frontend/src/api/strategy-tests.api.ts` for all strategy-test calls. Do not add new work to the legacy `strategy_lab` UI/API path unless the task is explicitly compatibility maintenance.

## Hard Rules

- Frontend displays only. It must not calculate trading eligibility, position size, stop loss, take profit, risk amount, R:R, liquidation, fees, slippage, PnL, or execution readiness.
- Frontend sends only intents: confirm virtual, confirm real, arm pending entry, cancel/reconfirm pending entry, reject signal, update settings, sync exchange data.
- Do not hardcode user ids, risk values, leverage, account balances, exchange execution parameters, or safety overrides in UI code.
- Render backend blockers, warnings, reason codes, and action state as received.
- Use generated OpenAPI types for request/response shapes.
- Keep trading actions disabled when backend action state or realtime freshness says they are unavailable.
