# Prompt 2 Mandatory Action Reasons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make disabled signal action and pending-entry rows always show concrete backend-owned reasons.

**Architecture:** Add a backend reason helper, wire it into action-state fallback paths, derive missing pending-entry terminal reason codes in the repository, and make frontend queues/actions use reason-code dictionaries instead of placeholder strings.

**Tech Stack:** Python unittest/Pydantic/SQLAlchemy, React/TypeScript/Vitest.

---

## File Structure

- Create `backend/app/services/signal_action_reason.py`: shared reason-selection helper.
- Modify `backend/app/services/signal_actions.py`: use helper for disabled fallback blockers.
- Modify `backend/app/domain/pending_entry_reason.py`: expose terminal status fallback reason-code derivation.
- Modify `backend/app/repositories/pending_entry_repository.py`: derive missing terminal/reconfirmation reason code and view.
- Modify `backend/tests/test_signal_action_state.py`: backend action-state and helper tests.
- Modify `backend/tests/test_pending_entry_trigger_service.py`: repository terminal fallback reason test.
- Modify `frontend/src/components/SignalDetails.tsx`: explicit disabled captions for enter-now and pending wait.
- Modify `frontend/src/features/app-shell/RadarPage.tsx`: pending queue reason-code fallback.
- Modify `frontend/src/i18n/dictionary.ts`: reason translations and remove placeholder usage.
- Modify `frontend/src/components/SignalDetails.test.tsx`: disabled captions test.
- Modify `frontend/src/features/app-shell/RadarPage.test.tsx`: pending queue fallback test.

## Tasks

### Task 1: Backend RED Tests

- [ ] Add `test_signal_action_reason_prioritizes_execution_gate_blocker` to `backend/tests/test_signal_action_state.py`.
- [ ] Add `test_signal_action_state_always_has_disabled_reason` to `backend/tests/test_signal_action_state.py`.
- [ ] Add `test_pending_entry_view_derives_missing_reason_code` to `backend/tests/test_pending_entry_trigger_service.py`.
- [ ] Run `.\.venv\Scripts\python.exe -m unittest backend.tests.test_signal_action_state backend.tests.test_pending_entry_trigger_service -v`.
- [ ] Confirm the new tests fail because helper/repository fallback behavior is missing.

### Task 2: Backend GREEN Implementation

- [ ] Add `backend/app/services/signal_action_reason.py` with `main_execution_blocker()`, `pending_entry_disabled_reason()`, and `enter_now_disabled_reason()`.
- [ ] In `SignalActionService`, append helper-derived blockers whenever action availability is false and no blocker exists.
- [ ] In `pending_entry_reason.py`, add `pending_entry_fallback_reason_code(status)`.
- [ ] In `pending_entry_repository.py`, use stored reason first, then fallback status reason; always build a view for terminal/reconfirmation fallback statuses.
- [ ] Re-run backend tests and keep existing action-state tests green.

### Task 3: Frontend RED Tests

- [ ] Add a `SignalDetails.test.tsx` case where both virtual buttons are disabled and captions contain backend blocker text.
- [ ] Add a `RadarPage.test.tsx` case where an expired pending entry has no backend reason and the queue renders `Pending entry expired before entry touch`, never `Причина от backend отсутствует`.
- [ ] Run `corepack pnpm test src/components/SignalDetails.test.tsx src/features/app-shell/RadarPage.test.tsx`.
- [ ] Confirm the new tests fail before frontend implementation.

### Task 4: Frontend GREEN Implementation

- [ ] Update `SignalDetails.tsx` to render explicit disabled captions for both `can_enter_now` and `can_arm_pending`.
- [ ] Update `RadarPage.tsx` pending queue fallback to resolve reason codes from status instead of placeholder text.
- [ ] Add i18n reason entries for Prompt 2 codes in EN/RU.
- [ ] Re-run frontend tests and typecheck.

### Task 5: Verification and Commit

- [ ] Run backend focused unittest command.
- [ ] Run frontend focused Vitest command.
- [ ] Run `corepack pnpm typecheck`.
- [ ] Check `git status --short`.
- [ ] Commit with `feat: require action disabled reasons`.
