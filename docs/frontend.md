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

## Hard Rules

- Frontend displays only. It must not calculate trading eligibility, position size, stop loss, take profit, risk amount, R:R, liquidation, fees, slippage, PnL, or execution readiness.
- Frontend sends only intents: confirm virtual, confirm real, arm pending entry, cancel/reconfirm pending entry, reject signal, update settings, sync exchange data.
- Do not hardcode user ids, risk values, leverage, account balances, exchange execution parameters, or safety overrides in UI code.
- Render backend blockers, warnings, reason codes, and action state as received.
- Use generated OpenAPI types for request/response shapes.
- Keep trading actions disabled when backend action state or realtime freshness says they are unavailable.
