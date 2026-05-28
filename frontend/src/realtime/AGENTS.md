# Realtime Agent Guide

Realtime is event-driven. Components must not own socket message handling.

## Flow

```text
FastAPI Realtime Gateway
  -> native WebSocket client
  -> event router
  -> Zustand/TanStack Query cache
  -> focused UI update
```

REST provides the initial snapshot. WebSocket provides live updates. Reconnect triggers reconciliation.

## Event contract

Every standard event must include:

- `id`
- `type`
- `version`
- `timestamp`
- `payload`

When adding a new event:

1. Extend `src/realtime/event-types.ts`.
2. Extend `src/realtime/event-schemas.ts`.
3. Add routing in `src/realtime/event-router.ts`.
4. Add a focused test when the event changes store/cache behavior.

## Signal feed updates

- `signal.created`: add to `signal-store`, insert at top of active Query cache.
- `signal.updated`: apply `payload.patch` by `signalId`; do not replace the whole feed.
- `signal.invalidated`: mark/update the affected signal only.
- `signal.entry_touched`: update signal status, price store, and notification store.

## Connection behavior

- Use exponential backoff from `reconnect-policy.ts`.
- Use heartbeat and heartbeat timeout from `socket-client.ts`.
- Preserve `lastEventId` for replay-aware resubscribe.
- Reconnect must resubscribe and refresh snapshots through Query invalidation.
- Private WebSocket connections use a short-lived WS token from auth, not the refresh token.

## Do not

- Do not add socket listeners in UI components.
- Do not poll for new signals.
- Do not put high-frequency market ticks into broad React state.
- Do not bypass Zod validation for incoming realtime payloads.
