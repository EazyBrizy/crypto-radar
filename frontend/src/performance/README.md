# Performance budget

Radar constraints:

- Initial dashboard render: under 1.5s target.
- Realtime event apply on frontend: under 100ms target.
- WebSocket reconnect: automatic with backoff, heartbeat, lastEventId, and resubscribe.
- Large lists: virtualized with TanStack Virtual.
- Price ticks: isolated in the price store, not full dashboard rerenders.
- Route bundle split: App Router routes keep heavy chunks out of unrelated pages.
- Charts: lazy-loaded and not imported by Settings.

UI constraints:

- Trade Journal requests status-filtered data instead of loading every trade by default.
- Signal Details chart uses a lazy client chunk.
- Heavy analytics lives behind a separate dynamic chunk.
