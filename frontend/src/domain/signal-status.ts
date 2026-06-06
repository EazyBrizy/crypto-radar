import type { RadarSignal, RiskCheckStatus, SignalFeedKind, SignalStatus } from "@/types";

export type SignalUiBadgeTone = "green" | "red" | "yellow" | "blue" | "purple" | "neutral";
export type RadarStatusFilter = "all" | SignalStatus;

export const SIGNAL_STATUSES = [
  "new",
  "active",
  "watchlist",
  "ready",
  "wait_for_pullback",
  "entry_touched",
  "actionable",
  "confirmed",
  "rejected",
  "expired",
  "invalidated",
  "closed"
] as const satisfies readonly SignalStatus[];

export const OPEN_SIGNAL_STATUSES = [
  "new",
  "active",
  "watchlist",
  "ready",
  "wait_for_pullback",
  "entry_touched",
  "actionable"
] as const satisfies readonly SignalStatus[];

export const MARKET_OPPORTUNITY_STATUSES: readonly SignalStatus[] = OPEN_SIGNAL_STATUSES;

export const WAITING_ENTRY_STATUSES = [
  "new",
  "active",
  "watchlist",
  "ready",
  "wait_for_pullback"
] as const satisfies readonly SignalStatus[];

export const EXECUTION_CANDIDATE_STATUSES = [
  "entry_touched",
  "actionable",
  "confirmed"
] as const satisfies readonly SignalStatus[];

export const TERMINAL_SIGNAL_STATUSES = [
  "invalidated",
  "expired",
  "closed",
  "rejected"
] as const satisfies readonly SignalStatus[];

export const RADAR_STATUS_FILTERS = [
  "all",
  "watchlist",
  "ready",
  "actionable",
  "wait_for_pullback",
  "invalidated",
  "expired"
] as const satisfies readonly RadarStatusFilter[];

const MARKET_OPPORTUNITY_STATUS_SET = new Set<SignalStatus>(MARKET_OPPORTUNITY_STATUSES);
const WAITING_ENTRY_STATUS_SET = new Set<SignalStatus>(WAITING_ENTRY_STATUSES);
const EXECUTION_CANDIDATE_STATUS_SET = new Set<SignalStatus>(EXECUTION_CANDIDATE_STATUSES);
const TERMINAL_SIGNAL_STATUS_SET = new Set<SignalStatus>(TERMINAL_SIGNAL_STATUSES);

export function isMarketOpportunity(status: SignalStatus): boolean {
  return MARKET_OPPORTUNITY_STATUS_SET.has(status);
}

export function isWaitingEntry(status: SignalStatus): boolean {
  return WAITING_ENTRY_STATUS_SET.has(status);
}

export function isExecutionCandidateStatus(status: SignalStatus): boolean {
  return EXECUTION_CANDIDATE_STATUS_SET.has(status);
}

export function isTerminalSignalStatus(status: SignalStatus): boolean {
  return TERMINAL_SIGNAL_STATUS_SET.has(status);
}

export function isEntryTouched(status: SignalStatus): boolean {
  return status === "entry_touched";
}

export function isExecutionReady(
  status: SignalStatus,
  _decision?: RadarSignal["decision"] | null,
  canEnter?: boolean | null
): boolean {
  return isExecutionCandidateStatus(status) && canEnter === true;
}

export function canShowEnterButton(signal: RadarSignal | null): boolean {
  if (!signal) return false;
  if (signal.execution_gate) return signal.execution_gate.can_enter_now === true;
  return signal.details_view?.can_enter_now === true;
}

export function signalFeedKind(signal: RadarSignal): SignalFeedKind {
  if (signal.execution_gate?.feed_kind) return signal.execution_gate.feed_kind;
  if (signal.details_view?.primary_status === "blocked") return "blocked";
  if (signal.details_view?.primary_status === "execution_ready") return "execution_signal";
  if (signal.status === "watchlist" || signal.status === "ready" || signal.status === "wait_for_pullback") {
    return "watchlist";
  }
  if (isExecutionCandidateStatus(signal.status) && signal.can_enter === true) return "execution_signal";
  if (isTerminalSignalStatus(signal.status)) return "blocked";
  return "market_idea";
}

export function isExecutionFeedSignal(signal: RadarSignal): boolean {
  if (signal.execution_gate) return signal.execution_gate.can_show_in_execution_feed === true;
  return signalFeedKind(signal) === "execution_signal";
}

export function isWatchlistSignal(signal: RadarSignal): boolean {
  return signalFeedKind(signal) === "watchlist";
}

export function isBlockedSignal(signal: RadarSignal): boolean {
  return signalFeedKind(signal) === "blocked";
}

export function isFormingCandleSignal(signal: RadarSignal): boolean {
  return signal.candle_state === "open";
}

export function isOpenCandleActionableAllowed(signal: RadarSignal): boolean {
  if (!isFormingCandleSignal(signal)) return true;
  return signal.details_view?.risk_summary.open_candle_allowed === true;
}

export function canShowSignalEntryAction(signal: RadarSignal): boolean {
  if (signal.execution_gate) return signal.execution_gate.can_enter_now === true;
  if (!canShowEnterButton(signal)) return false;
  return !isFormingCandleSignal(signal) || isOpenCandleActionableAllowed(signal);
}

export function statusBadgeTone(
  signal: RadarSignal,
  previewOnly = false
): SignalUiBadgeTone {
  if (previewOnly) return "yellow";
  if (signal.card_view?.status_tone) return signal.card_view.status_tone;
  if (isEntryTouched(signal.status)) return "purple";
  if (isWaitingEntry(signal.status)) return signal.status === "watchlist" ? "yellow" : "blue";
  if (isTerminalSignalStatus(signal.status)) return "red";
  return "neutral";
}

export function statusBadgeLabel(signal: RadarSignal, previewOnly = false): string {
  if (previewOnly) return "preview";
  if (signal.card_view?.status_label) return signal.card_view.status_label;
  if (isEntryTouched(signal.status)) return "Entry touched";
  if (isWaitingEntry(signal.status)) return "Waiting entry";
  if (isMarketOpportunity(signal.status)) return "Market opportunity";
  return signal.status.replaceAll("_", " ");
}

export function marketOpportunityLabel(signal: RadarSignal): string {
  if (signal.card_view?.opportunity_label) return signal.card_view.opportunity_label;
  if (isEntryTouched(signal.status)) return "Entry touched";
  if (isWaitingEntry(signal.status)) return "Waiting entry";
  if (isMarketOpportunity(signal.status)) return "Market opportunity";
  return signal.status.replaceAll("_", " ");
}

export function marketOpportunityTone(signal: RadarSignal): SignalUiBadgeTone {
  if (signal.card_view?.opportunity_tone) return signal.card_view.opportunity_tone;
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
