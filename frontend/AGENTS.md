# Frontend Agent Guide

This frontend is a Next.js App Router SaaS shell with realtime trading UI. Keep changes aligned with the existing event-driven architecture.

## Core rules

- Use `pnpm` through Corepack. Do not add npm/yarn lockfiles.
- Keep Next.js responsible for routing, SaaS shell, auth UI, billing, and frontend runtime only.
- FastAPI remains the source of trading data, signal logic, risk logic, exchange state, REST, WebSocket, and SSE.
- Do not route realtime signals through Next.js API routes unless there is a very explicit product reason.

## Data ownership

- REST/server state belongs in TanStack Query:
  - API files: `src/api/*.api.ts`
  - query keys: `src/features/server-state/query-keys.ts`
  - hooks: `src/features/server-state/use-server-state.ts`
- Local UI/realtime state belongs in Zustand:
  - `src/stores/ui-store.ts`
  - `src/stores/signal-store.ts`
  - `src/stores/price-store.ts`
  - `src/stores/notification-store.ts`
- Do not duplicate server state in Zustand unless it is a realtime-optimized normalized projection.

## Feature workflow

- New REST feature:
  1. Update/generate OpenAPI types.
  2. Add or extend `src/api/*.api.ts`.
  3. Add query keys.
  4. Add a TanStack Query hook.
  5. Render through route/client components.
- New realtime feature:
  1. Add event type.
  2. Add Zod validation.
  3. Route in `event-router.ts`.
  4. Update store/query cache.
  5. Add notification only when user-visible.

## Performance rules

- No polling for live signals.
- No `ws.onmessage` inside React components.
- No full dashboard rerender for price ticks.
- Large lists must use virtualization.
- Charts must be lazy-loaded and must not enter Settings or shell bundles.
- Heavy analytics must be a separate dynamic chunk.

## UI rules

- Use existing Tailwind/shadcn/Radix/Lucide patterns.
- Add reusable primitives to `src/components/ui`.
- Trading actions must respect realtime freshness and disabled-state selectors.
- Keep dashboards quiet, dense, and operational; avoid landing-page styling inside app workflows.
