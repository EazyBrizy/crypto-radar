import type { RadarSignal, RiskCheckStatus, SignalStatus } from "@/types";

export type SignalUiBadgeTone = "green" | "red" | "yellow" | "blue" | "purple" | "neutral";

const MARKET_OPPORTUNITY_STATUSES = new Set<SignalStatus>([
  "new",
  "active",
  "watchlist",
  "ready",
  "actionable",
  "wait_for_pullback",
  "entry_touched"
]);

const WAITING_ENTRY_STATUSES = new Set<SignalStatus>([
  "new",
  "active",
  "watchlist",
  "ready",
  "wait_for_pullback"
]);

export function isMarketOpportunity(status: SignalStatus): boolean {
  return MARKET_OPPORTUNITY_STATUSES.has(status);
}

export function isWaitingEntry(status: SignalStatus): boolean {
  return WAITING_ENTRY_STATUSES.has(status);
}

export function isEntryTouched(status: SignalStatus): boolean {
  return status === "entry_touched";
}

export function isExecutionReady(
  status: SignalStatus,
  decision?: RadarSignal["decision"] | null,
  canEnter?: boolean | null
): boolean {
  const entryStatus = status === "actionable" || status === "entry_touched";
  if (!entryStatus) return false;
  if (canEnter === false) return false;
  if (canEnter === true) return true;
  if (decision) {
    return decision.signal_actionable === true
      && decision.execution_allowed_virtual !== false
      && !decision.blockers.length
      && entryStatus;
  }
  return false;
}

export function canShowEnterButton(signal: RadarSignal | null): boolean {
  if (!signal) return false;
  return isExecutionReady(signal.status, signal.decision, signal.can_enter);
}

export function statusBadgeTone(
  signal: RadarSignal,
  previewOnly = false
): SignalUiBadgeTone {
  if (previewOnly) return "yellow";
  if (isExecutionReady(signal.status, signal.decision, signal.can_enter)) return "green";
  if (isEntryTouched(signal.status)) return "purple";
  if (isWaitingEntry(signal.status)) return signal.status === "watchlist" ? "yellow" : "blue";
  if (signal.status === "invalidated" || signal.status === "expired" || signal.status === "rejected") return "red";
  return "neutral";
}

export function statusBadgeLabel(signal: RadarSignal, previewOnly = false): string {
  if (previewOnly) return "preview";
  if (isExecutionReady(signal.status, signal.decision, signal.can_enter)) return "Execution-ready";
  if (isEntryTouched(signal.status)) return "Entry touched";
  if (isWaitingEntry(signal.status)) return "Waiting entry";
  if (isMarketOpportunity(signal.status)) return "Market opportunity";
  return signal.status.replaceAll("_", " ");
}

export function marketOpportunityLabel(signal: RadarSignal): string {
  if (isExecutionReady(signal.status, signal.decision, signal.can_enter)) return "Execution-ready";
  if (signal.risk_gate_status === "failed" || signal.can_enter === false) return "Risk blocked";
  if (isEntryTouched(signal.status)) return "Entry touched";
  if (isWaitingEntry(signal.status)) return "Waiting entry";
  if (isMarketOpportunity(signal.status)) return "Market opportunity";
  return signal.status.replaceAll("_", " ");
}

export function marketOpportunityTone(signal: RadarSignal): SignalUiBadgeTone {
  if (isExecutionReady(signal.status, signal.decision, signal.can_enter)) return "green";
  if (signal.risk_gate_status === "failed" || signal.can_enter === false) return "red";
  if (isEntryTouched(signal.status)) return "purple";
  if (isWaitingEntry(signal.status)) return "blue";
  if (isMarketOpportunity(signal.status)) return "yellow";
  return "neutral";
}

export function riskGateTone(status: RiskCheckStatus | null | undefined): SignalUiBadgeTone {
  if (status === "passed") return "green";
  if (status === "failed") return "red";
  if (status === "warning") return "yellow";
  return "neutral";
}
