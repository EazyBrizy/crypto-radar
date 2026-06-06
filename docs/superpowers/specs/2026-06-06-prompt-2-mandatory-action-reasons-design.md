# Prompt 2 Mandatory Action Reasons Design

## Goal

Every disabled signal action and pending-entry terminal row must expose a concrete, user-facing reason. The UI must never show the placeholder "Причина от backend отсутствует".

## Current State

- `SignalActionService.state_for_signal()` already returns `SignalActionState.disabled_reason_code`, `blockers`, and `display_labels`.
- Execution-gate blockers already carry reason code, source, severity, message, and metadata.
- Pending-entry repository reads reason codes from `request_snapshot`, but terminal rows with missing stored reason codes can return no view and no derived reason.
- `PendingEntriesQueue` currently falls back to `pendingEntry.noReasonFromBackend`.

## Backend Design

Add `backend/app/services/signal_action_reason.py` as the shared reason helper. It returns a small dict with `code`, `message`, `source`, and `severity`.

Priority:

1. First `execution_gate.reasons` item with `severity == "blocker"`.
2. Known execution-gate/action codes in this order: `forming_candle`, `trigger_not_confirmed`, `edge_unknown`, `edge_missing`, `trade_plan_incomplete`, `no_trade_hard_block`, `rr_failed`, `decision_not_actionable`, `virtual_execution_blocked`, `terminal_signal`.
3. Fallback `execution_gate_blocked`.

`SignalActionService` uses this helper when an action is disabled and no blocker was already produced. That keeps existing risk/account blockers authoritative while ensuring disabled action state is never silent.

`PendingEntryIntentRepository` derives missing terminal reason codes:

- `expired` -> `pending_entry_expired_before_touch`
- `cancelled` -> `cancelled`
- `failed` -> `execution_failed`
- `requires_reconfirmation` -> `trade_plan_reconfirmation_required`

The repository always builds a `PendingEntryView` when a reason code exists or a terminal/reconfirmation status needs a reason.

## Frontend Design

`SignalDetails` keeps backend action-state as source of truth. Disabled captions use:

1. `actionState.disabled_reason_code`
2. first action-state blocker
3. execution-gate blocker

The pending-entry button caption remains explicit through `waitingEntryUnavailable`; enter-now also gets an explicit disabled caption.

`PendingEntriesQueue` resolves reason text from `view.reason`, `view.reason_code`, `reason_code`, or a status-derived reason code. It never reads or renders the old backend-missing placeholder.

`dictionary.ts` adds translations for the Prompt 2 reason codes.

## Tests

Backend:

- `test_signal_action_state_always_has_disabled_reason`
- `test_pending_entry_view_derives_missing_reason_code`
- `test_signal_action_reason_prioritizes_execution_gate_blocker`

Frontend:

- `SignalDetails.test.tsx` verifies disabled virtual wait/entry captions show blocker reasons.
- `RadarPage.test.tsx` verifies pending queue does not render the old placeholder and uses reason-code fallback text.

## Acceptance

- Disabled action buttons are never silent.
- Pending queue never shows "Причина от backend отсутствует".
- Users see concrete labels for forming candle, unknown/missing edge, trigger not confirmed, and incomplete trade plan.
