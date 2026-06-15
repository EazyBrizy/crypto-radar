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

Strategy Testing request/response unions in `frontend/src/features/strategy-testing/types.ts` should derive from `frontend/src/api/generated/openapi-types.ts` where possible. Keep local types as UI-facing adapters only; do not redefine backend status, test type, active-run, or same-candle-policy contracts by hand.

## Runtime Env

- `NEXT_PUBLIC_FASTAPI_HTTP_URL`: FastAPI HTTP origin.
- `NEXT_PUBLIC_FASTAPI_WS_URL`: FastAPI realtime WebSocket URL.
- `NEXT_PUBLIC_FASTAPI_SSE_URL`: FastAPI realtime SSE fallback URL.
- `NEXT_PUBLIC_FASTAPI_TIMEOUT_MS`: frontend request timeout.

## Pages

- Radar: `frontend/src/app/dashboard/radar/page.tsx`, controller in `frontend/src/features/app-shell/RadarRoute.tsx`, view in `frontend/src/features/app-shell/RadarPage.tsx`.
- Watchlist: `frontend/src/app/dashboard/watchlist/page.tsx`, `frontend/src/features/app-shell/WatchlistRoute.tsx`, `frontend/src/features/app-shell/WatchlistPage.tsx`.
- Trades: `frontend/src/app/dashboard/trades/page.tsx`, subroutes in `frontend/src/app/dashboard/trades/active/page.tsx`, `frontend/src/app/dashboard/trades/journal/page.tsx`, `frontend/src/app/dashboard/trades/analytics/page.tsx`, controller in `frontend/src/features/app-shell/TradesRoute.tsx`, view in `frontend/src/features/app-shell/TradesPage.tsx`.
- Settings: `frontend/src/app/dashboard/settings/page.tsx`, `frontend/src/features/app-shell/SettingsRoute.tsx`, `frontend/src/features/app-shell/SettingsPage.tsx`.
- Auth and billing: `frontend/src/app/auth/page.tsx`, `frontend/src/app/billing/page.tsx`.

## UI Blocks

- Signal feed: `frontend/src/components/SignalFeed.tsx`, `frontend/src/components/SignalCard.tsx`.
- Signal details and action state: `frontend/src/components/SignalDetails.tsx`, `frontend/src/components/signal-details-view-model.ts`.
- Pending entries queue: `PendingEntriesQueue` inside `frontend/src/features/app-shell/RadarPage.tsx`.
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

## Strategy Testing Fields

- Strategy test run responses include backend-owned `test_type`, `status`, `summary`, `runtime_state`, and `last_heartbeat_at`.
- The Strategy Testing panel must call the backend active-run endpoint and display `can_run`, `disabled_reason`, `disabled_reason_code`, `is_stale`, `stale_threshold_seconds`, and `allowed_actions` as received.
- The Run button is enabled only when the backend active-run response says `can_run=true` and the local form is valid. Active-run stale detection is not a frontend calculation.
- Cancel and refresh controls are rendered from backend active-run state and allowed actions; cancelling a run calls the backend cancel endpoint.
- The frontend may display these fields and form validation state, but it must not compute stale decisions, eligibility, risk, PnL, or execution readiness.
- `forward_virtual` and `historical_backtest` are API values from the backend contract, not separate frontend workflows.
- For fronttests, display backend `runtime_state.status` and counters such as `processed_ticks`, `processed_signals`, `opened_trades`, `trades_written`, and `metrics_written` as received. Common runtime statuses include `listening`, `processing`, `degraded`, and `cancelled`; the backend owns their meaning.
- `StrategyTestingPanel.test.tsx` is the UI contract smoke for active-run behavior: backend reasons are shown, Run is disabled or enabled from `can_run`, and stale or active runs can be cancelled only when `allowed_actions` includes `cancel`.

## Execution Rendering Contract

The Radar UI displays backend execution state. It must not recompute whether a signal is executable.

- Use `signal.execution_gate` as the source of truth for execution feed visibility, action availability, blockers, warnings, and reason codes.
- Use backend `action_state`, `card_view`, and `details_view` as display-ready JSON DTOs. They are rendered state, not inputs for frontend trading calculations.
- Use `signal.trigger` only as display context for confirmed or rejected trigger state.
- Use `signal.edge.metadata.strategy_eligibility` only as display context for strategy eligibility.
- Use `signal.execution_gate.metadata.dedup` only as display context for keep/suppress/replace decisions.
- Use pending-entry `view.reason_code` and backend terminal metadata for no-entry, rejected, expired, or temporary-failure outcomes.
- The Radar route starts in `all_market_opportunities`; `execution_ready` is an explicit user-selected filter for the execution feed.
- `signal.execution_ready` means the backend approved an execution-ready notification. Legacy `signal.created` is displayed as a non-execution idea unless its payload explicitly says otherwise.
- Signal cards and details should render backend blockers such as `forming_candle`, `trigger_not_confirmed`, `dedup_suppressed_by_better_signal`, strategy eligibility failures, and pending-entry terminal reasons without doing trading math.
- Do not infer `can_enter`, `can_run`, disabled reasons, stale decisions, PnL, or risk state from raw signal snapshots. Display the backend fields that already carry those decisions.

## Hard Rules

- Frontend displays only. It must not calculate trading eligibility, position size, stop loss, take profit, risk amount, R:R, liquidation, fees, slippage, PnL, or execution readiness.
- Frontend sends only intents: confirm virtual, confirm real, arm pending entry, cancel/reconfirm pending entry, reject signal, update settings, sync exchange data.
- Do not hardcode user ids, risk values, leverage, account balances, exchange execution parameters, or safety overrides in UI code.
- Render backend blockers, warnings, reason codes, and action state as received.
- Use generated OpenAPI types for request/response shapes.
- Keep trading actions disabled when backend action state or realtime freshness says they are unavailable.
