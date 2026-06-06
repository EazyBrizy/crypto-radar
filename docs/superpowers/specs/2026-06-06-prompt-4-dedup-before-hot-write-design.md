# Prompt 4 Dedup Before Hot Write Design

## Goal

Ensure write-side deduplication runs before analytics, Redis hot-store, and worker-created realtime/notification side effects see the signal.

## Current State

- `SignalService.upsert_strategy_signal()` writes the raw repository result to analytics/hot-store before `_apply_write_side_dedup()`.
- Suppressed duplicates can briefly appear as execution candidates in Redis/pubsub before being terminally updated.
- Worker created-event and notification decisions depend on the final `RadarSignal`, but `created=True` still causes created-event publication unless guarded.

## Backend Design

Signal service:

- Change `upsert_strategy_signal()` order to:
  1. repository upsert,
  2. write-side dedup,
  3. `_after_write(final_result)`,
  4. pending-entry reconciliation,
  5. return final signal and original `created` flag.
- Keep replaced-signal transitions inside `_apply_write_side_dedup()` writing through `_after_write(replaced)`.
- For suppressed candidates, transition to Prompt 3 terminal status `rejected` and attach a blocked execution gate:
  - `feed_kind="blocked"`
  - `can_notify=False`
  - `can_show_in_execution_feed=False`
  - `metadata.dedup.action="suppress"`
  - `metadata.dedup.dedup_lifecycle="dedup_suppressed"`

Dedup metadata:

- Keep `action` simple for consumers: `keep`, `suppress`, `replace`.
- Add `dedup_lifecycle` for explicit lifecycle/audit classification: `dedup_suppressed`, `dedup_replace`, or `dedup_replaced`.

Signal worker:

- Add a small helper that detects `execution_gate.metadata.dedup.action == "suppress"`.
- Skip created-event publication for suppressed duplicates even when `created=True`.
- Refuse notifications for suppressed duplicates even if stale gate fields look execution-ready.

## Tests

- `test_signal_service_dedup_applies_before_hot_store_write`
- `test_signal_worker_no_created_event_for_suppressed_duplicate`
- `test_signal_worker_no_notification_for_suppressed_duplicate`
- Existing dedup tests assert suppressed/replaced metadata and terminal statuses.

## Acceptance

- Hot-store and analytics receive only the post-dedup final candidate result.
- Suppressed duplicate cards do not flash as realtime created events.
- Suppressed duplicates are never notification-eligible.
