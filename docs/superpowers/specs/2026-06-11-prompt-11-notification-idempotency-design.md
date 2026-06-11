# Prompt 11 Notification Idempotency Design

## Objective

Prevent duplicate execution notifications for the same user, exchange, symbol, and direction within the configured dedup window, even after scanner restart or across multiple workers.

## Key

Use:

```text
user_id + exchange + normalized_symbol + direction + execution_signal + time_bucket
```

where:

```text
time_bucket = floor(now / settings.notification_dedup_window_seconds)
```

## Storage

Primary storage is Redis:

```text
SET key value NX EX notification_dedup_window_seconds
```

If Redis is unavailable, fall back to service-local in-memory dedup and log a warning. The fallback keeps the current single-process behavior but does not pretend to solve cross-worker idempotency without Redis.

## Integration

`NotificationService.create_signal_notification(signal, user_id)` owns the dedup decision by calling `should_create_execution_notification(signal, user_id)` before writing a notification record.

`create_notification()` remains unchanged for system/test notifications.

`signal_worker` may keep its in-memory eligibility/dedup as a secondary pre-filter, but service-level dedup is authoritative.
