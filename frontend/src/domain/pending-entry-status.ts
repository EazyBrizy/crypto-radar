import type { PendingEntryIntentStatus } from "@/types";

export const ACTIVE_PENDING_ENTRY_STATUSES = [
  "pending",
  "triggered",
  "filling",
  "requires_reconfirmation"
] as const satisfies readonly PendingEntryIntentStatus[];

export const TERMINAL_PENDING_ENTRY_STATUSES = [
  "filled",
  "failed",
  "cancelled",
  "expired"
] as const satisfies readonly PendingEntryIntentStatus[];

const ACTIVE_PENDING_ENTRY_STATUS_SET = new Set<PendingEntryIntentStatus>(ACTIVE_PENDING_ENTRY_STATUSES);
const TERMINAL_PENDING_ENTRY_STATUS_SET = new Set<PendingEntryIntentStatus>(TERMINAL_PENDING_ENTRY_STATUSES);

export function isActivePendingEntryStatus(status: PendingEntryIntentStatus): boolean {
  return ACTIVE_PENDING_ENTRY_STATUS_SET.has(status);
}

export function isTerminalPendingEntryStatus(status: PendingEntryIntentStatus): boolean {
  return TERMINAL_PENDING_ENTRY_STATUS_SET.has(status);
}
