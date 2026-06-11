# Prompt 11 Notification Idempotency Plan

## Goal

Move execution notification dedup from scanner-worker memory to `NotificationService` using Redis `SET NX EX`, with in-memory fallback when Redis is unavailable.

## Task 1: RED Tests

- [x] Add notification service tests:
  - `test_notification_service_suppresses_duplicate_execution_signal`
  - `test_notification_service_allows_after_window`

- [x] Add worker restart simulation:
  - `test_signal_worker_no_duplicate_after_restart_simulation`
  - The worker eligibility set is recreated, but `NotificationService` still suppresses the second notification.

- [x] Run RED:

```powershell
$env:PYTHONPATH='C:\Users\gvenv\Desktop\crypto-radar\backend'; C:\Users\gvenv\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_notification_service_contract tests.test_signal_worker_notifications -v
```

Expected: new tests fail because service-level idempotency does not exist.

## Task 2: GREEN Implementation

- [x] Extend `NotificationService.__init__`
  - Add injectable `redis_client_factory` and clock for deterministic tests.
  - Keep existing defaults unchanged.

- [x] Add `should_create_execution_notification(signal, user_id)`
  - Build bucketed key.
  - Try Redis `set(..., nx=True, ex=window)`.
  - Return `False` on duplicate.
  - On Redis error, log warning and use in-memory fallback.

- [x] Update `create_signal_notification`
  - Return `None` when duplicate is suppressed.
  - Keep `create_notification` unchanged.

- [x] Leave worker eligibility as secondary
  - No API/system notification behavior changes.

- [x] Run GREEN command from Task 1.

## Task 3: Verification And Commit

- [x] Run:

```powershell
$env:PYTHONPATH='C:\Users\gvenv\Desktop\crypto-radar\backend'; C:\Users\gvenv\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_notification_service_contract tests.test_signal_worker_notifications tests.test_realtime_event_schema -v
git diff --check
```

- [x] Commit:

```powershell
git add backend/app/services/notification_service.py backend/tests/test_notification_service_contract.py backend/tests/test_signal_worker_notifications.py docs/superpowers/specs/2026-06-11-prompt-11-notification-idempotency-design.md docs/superpowers/plans/2026-06-11-prompt-11-notification-idempotency.md
git commit -m "feat: add redis notification idempotency"
```
