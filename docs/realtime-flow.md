# Realtime Signal Flow

Signal delivery is backend-push first. The frontend does not ask whether new
signals exist on a tight interval.

Flow:

1. Signal Engine detects or refreshes a signal.
2. FastAPI stores the signal through the signal service.
3. FastAPI publishes a versioned realtime event to the message broker.
4. Realtime Gateway consumes broker events.
5. Realtime Gateway pushes events to subscribed WebSocket clients.
6. Frontend event router receives the event.
7. TanStack Query cache is updated.
8. Radar renders the new signal card at the top.

Frontend data loading remains split:

- initial active snapshot: REST `GET /api/v1/signals/active`
- live updates: WebSocket
- reconciliation: rare REST refresh after reconnect or on a 1-5 minute interval

The current broker implementation is in-process for local development. Its
interface is intentionally isolated so Redis, Kafka, or NATS can replace it
without changing scanner workers, API handlers, or frontend realtime code.

Every realtime event uses the same envelope:

```json
{
  "id": "evt_01HX...",
  "type": "signal.created",
  "version": 1,
  "timestamp": "2026-05-25T10:12:41.231Z",
  "payload": {}
}
```

Supported event types:

- `signal.created`
- `signal.updated`
- `signal.invalidated`
- `trade.activated`
- `trade.closed`
- `price.touched_entry`
- `order.status_changed`
- `connection.heartbeat`

The envelope makes events deduplicatable, replayable, loggable, and testable.
