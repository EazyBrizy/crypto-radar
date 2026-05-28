# Frontend Server State

`server-state` is the boundary for data owned by FastAPI and fetched over REST.
TanStack Query owns cache, background refresh, de-duplication, stale data, and
mutation invalidation for this layer.

Use this layer for:

- user profile
- settings and radar config
- watchlist
- journal history
- closed trades
- subscription status
- historical signals
- exchange connection/catalog state

Do not put these values in Zustand. Zustand is reserved for UI and realtime-only
client state: selected signal, local filters, active panels, connection status,
and ephemeral websocket state.

Realtime WebSocket events should patch the TanStack Query cache by query key.
The initial load and historical data still come from REST.
