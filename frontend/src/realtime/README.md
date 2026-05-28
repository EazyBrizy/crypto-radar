# Realtime Layer

Frontend realtime is intentionally outside React components.

Flow:

1. TanStack Query performs the initial REST snapshot, for example `GET /api/v1/signals/active`.
2. `socket-client.ts` opens the native WebSocket connection and optional SSE read-only fallback.
3. `subscriptions.ts` sends the live subscription message.
4. `heartbeat.ts` sends periodic pings while the socket is open.
5. `event-router.ts` routes incoming events into TanStack Query caches and UI heartbeat markers.
6. TanStack Query performs rare reconciliation, not frequent UI polling.
7. Components read data through TanStack Query hooks and local UI state through Zustand selectors.

The contract is:

- initial snapshot through REST
- live updates through WebSocket
- rare reconciliation after reconnect or on an interval such as 1-5 minutes
- every pushed event has `id`, `type`, `version`, `timestamp`, and `payload`

Do not attach `ws.onmessage` inside a component. Components should only mount the gateway and render selected state.

Rendering rules:

- Radar uses a normalized signal store: `signalsById` plus `signalIds`.
- Signal cards subscribe to one signal by id instead of receiving the whole feed.
- Signal Feed is virtualized with TanStack Virtual.
- Price updates use a separate store and are batched with `requestAnimationFrame`.
- High-frequency price events must not rewrite the signal object.
