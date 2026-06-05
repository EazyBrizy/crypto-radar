# Crypto Radar Frontend

Next.js App Router frontend for the Crypto Radar SaaS shell and realtime trading UI.

## Runtime

- Node.js 24.16.0
- Corepack
- pnpm 10
- Next.js App Router
- React Client Components for realtime screens
- Tailwind CSS
- shadcn/ui + Radix primitives
- TanStack Query
- Zustand
- OpenAPI-generated TypeScript client
- Lightweight Charts
- TanStack Table + Virtual
- React Hook Form + Zod
- ESLint

The project is intentionally strict about the runtime:

```powershell
node -v
corepack pnpm --version
```

Expected Node range is declared in `package.json`: `>=24.16.0 <25`.

## Responsibility Split

Next.js owns UI, routing, SaaS shell, SSR-friendly pages, settings, auth shell, billing and onboarding.

FastAPI owns market data, signal engine, strategy engine, exchange connectors, paper trading, real trade sync, risk engine, REST API and realtime gateway.

Trading mode semantics and backend safety gates are documented in `../README.md`,
`../docs/BACKEND.md`, and `../docs/FRONTEND.md`. The frontend should treat real
exchange order placement as a backend-controlled capability; browser code must
not store exchange API secrets or infer mainnet readiness locally.

Critical signal flow should stay direct:

```text
Signal Engine
  -> FastAPI Realtime Gateway
  -> Browser WebSocket / SSE
  -> Frontend Realtime Store
  -> Radar UI
```

Node.js / Next.js must not be an extra realtime proxy unless a specific BFF feature needs it.

## Local Development

```powershell
cd frontend
corepack pnpm install
corepack pnpm dev
```

`dev` starts Next.js and then warms the main dashboard routes. This is intentional: Next dev compiles routes on demand, so warming moves the slow first compile into startup instead of the first click. If you need raw Next.js behavior, use:

```powershell
corepack pnpm dev:next
```

Open:

```text
http://127.0.0.1:3000
```

Backend default:

```text
http://127.0.0.1:8000
```

Override FastAPI URLs when needed:

```powershell
$env:NEXT_PUBLIC_FASTAPI_HTTP_URL="http://127.0.0.1:8000"
$env:NEXT_PUBLIC_FASTAPI_WS_URL="ws://127.0.0.1:8000/api/v1/realtime/ws"
$env:NEXT_PUBLIC_FASTAPI_SSE_URL="http://127.0.0.1:8000/api/v1/realtime/events"
corepack pnpm dev
```

`NEXT_PUBLIC_FASTAPI_WS_URL` and `NEXT_PUBLIC_FASTAPI_SSE_URL` are browser-facing URLs. They should point directly to FastAPI.

## Checks

```powershell
corepack pnpm lint
corepack pnpm test
corepack pnpm build
corepack pnpm test:e2e
```

## OpenAPI Client

The frontend client is generated from FastAPI OpenAPI:

```text
FastAPI /openapi.json
  -> src/api/generated/openapi.json
  -> src/api/generated/openapi-types.ts
  -> src/api/generated/schemas.ts
  -> src/api/client.ts
  -> src/hooks/use-radar-queries.ts
```

Regenerate after API schema changes:

```powershell
corepack pnpm openapi:generate
```

The exporter first tries `NEXT_PUBLIC_FASTAPI_HTTP_URL/openapi.json`, then falls back to importing the local FastAPI app.

## State Split

TanStack Query owns server state:

- health
- radar status
- radar feed
- signals
- trades
- config

Zustand owns UI and realtime state:

- active page
- selected signal id
- signal filter
- Trades tab
- WebSocket/SSE connection status
- last realtime event timestamp

Realtime messages from FastAPI update TanStack Query cache directly, so REST polling, manual refresh and WebSocket updates converge into one server-state source.

## Realtime Layer

Browser realtime uses a native WebSocket client:

```text
FastAPI WebSocket
  -> NativeRealtimeClient
  -> FastApiRealtimeGateway
  -> TanStack Query cache
  -> Radar UI
```

SSE is configured as a read-only fallback only:

```powershell
$env:NEXT_PUBLIC_FASTAPI_WS_URL="ws://127.0.0.1:8000/api/v1/realtime/ws"
$env:NEXT_PUBLIC_FASTAPI_SSE_URL="http://127.0.0.1:8000/api/v1/realtime/events"
```

The native client reconnects WebSocket with backoff and keeps SSE as a temporary public/read-only feed fallback.

## UI Wrappers

Reusable wrappers are ready for feature screens:

- `src/components/charts/ChartPanel.tsx` wraps TradingView Lightweight Charts.
- `src/components/data-table/DataTable.tsx` wraps TanStack Table and TanStack Virtual.
- `src/components/forms/form-pattern.tsx` wraps React Hook Form with Zod validation and Radix Label.

## Docker

Production profile:

```powershell
cd ../infra
docker compose --profile app up --build
```

Development profile with mounted source:

```powershell
cd ../infra
docker compose --profile dev up
```

Infrastructure only:

```powershell
cd ../infra
docker compose --profile infra up
```

The production frontend image uses Next.js standalone output. The browser still connects directly to FastAPI for realtime data.
