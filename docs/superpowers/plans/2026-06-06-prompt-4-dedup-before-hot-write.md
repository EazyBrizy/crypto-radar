# Prompt 4 Dedup Before Hot Write Implementation Plan

**Goal:** Move write-side dedup before hot-store/analytics side effects and suppress duplicate created events.

**Architecture:** Keep repository writes unchanged, but make `SignalService` publish only the final dedup-adjusted `SignalWriteResult`; expose suppressed duplicate metadata through `execution_gate.metadata.dedup` for worker guards.

## Tasks

- [x] Add RED tests for hot-store/analytics seeing pre-dedup state.
- [x] Add worker tests for suppressed created-event and notification guards.
- [x] Reorder `SignalService.upsert_strategy_signal()` so `_after_write()` receives final dedup result.
- [x] Add blocked execution gate metadata for suppressed duplicates.
- [x] Keep replaced-signal transition writes through `_after_write(replaced)`.
- [x] Add worker helper for `dedup.action == "suppress"`.
- [x] Run focused backend verification.
- [ ] Commit with `feat: dedupe signals before hot write`.
