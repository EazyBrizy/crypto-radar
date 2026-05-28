# Server State Agent Guide

This folder owns REST-backed server state via TanStack Query.

## Responsibilities

- Query keys live in `query-keys.ts`.
- Query policies live in `query-policy.ts`.
- Query/mutation hooks live in `use-server-state.ts`.
- Keep `src/hooks/use-radar-queries.ts` as a compatibility re-export.

## New REST data flow

1. Use FastAPI OpenAPI-generated types.
2. Add a domain API wrapper in `src/api`.
3. Add a stable query key.
4. Add a hook with the correct stale/refetch policy.
5. Use Query invalidation for reconciliation after reconnect or mutations.

## Separation rules

- TanStack Query owns server data, cache, background refresh, dedupe, and reconciliation.
- Zustand owns UI state, selections, layout, modals, realtime connection state, and normalized live projections.
- Realtime events may update Query cache directly when they are authoritative.
- Do not create parallel manual caches in components.

## Policy hints

- Active signals and radar status are realtime-sensitive.
- Historical signals, journal, settings, profile, subscription, and exchange connections are server state.
- Trade journal routes should request filtered data instead of loading all history by default.
