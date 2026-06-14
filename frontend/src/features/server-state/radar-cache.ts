import type { RadarResponse, RadarSignal, RadarSummary } from "@/types";
import type { RadarDisplayMode } from "@/features/server-state/types";
import { isOpenFeedSignal } from "@/utils";

export function buildRadarSummaryFrontend(signals: RadarSignal[]): RadarSummary {
  return {
    total_signals: signals.length,
    hot_signals: signals.filter(isHotSignal).length,
    armable_signals: signals.filter((signal) => signal.execution_gate?.can_arm_pending === true).length,
    execution_ready_signals: signals.filter((signal) => signal.execution_gate?.can_show_in_execution_feed === true || signal.details_view?.can_enter_now === true).length,
    watchlist_signals: signals.filter((signal) => signal.execution_gate?.feed_kind === "watchlist").length,
    market_ideas: signals.filter((signal) => signal.execution_gate?.feed_kind === "market_idea").length,
    high_confidence_signals: signals.filter((signal) => signal.score >= 80).length,
    positive_edge_signals: signals.filter((signal) => signal.edge?.status === "positive").length,
    blocked_diagnostics: signals.filter(isBlockedSignal).length,
    blocked_ideas: signals.filter(isBlockedSignal).length
  };
}

export function radarResponseWithSignals(
  signals: RadarSignal[],
  summary: RadarSummary | null | undefined = buildRadarSummaryFrontend(signals)
): RadarResponse {
  return {
    signals,
    summary: summary ?? buildRadarSummaryFrontend(signals)
  };
}

export function mergeRadarSnapshotWithRealtime(
  currentStoreSignals: RadarSignal[],
  snapshotSignals: RadarSignal[],
  snapshotReceivedAt: number,
  signalReceivedAtById: Record<string, number> = {},
  radarDisplayMode?: RadarDisplayMode | null
): RadarSignal[] {
  const currentById = new Map(currentStoreSignals.map((signal) => [signal.id, signal]));
  const snapshotOpenSignals = snapshotSignals
    .filter((signal) => isOpenFeedSignal(signal, snapshotReceivedAt))
    .filter((signal) => signalMatchesRadarDisplayMode(signal, radarDisplayMode))
    .map((snapshotSignal) => {
      const currentSignal = currentById.get(snapshotSignal.id);
      if (!currentSignal || !isOpenFeedSignal(currentSignal)) return snapshotSignal;
      const currentReceivedAt = signalReceivedAtById[currentSignal.id] ?? signalUpdatedAtMs(currentSignal);
      return currentReceivedAt > snapshotReceivedAt ? currentSignal : snapshotSignal;
    });
  const snapshotIds = new Set(snapshotOpenSignals.map((signal) => signal.id));
  const realtimeSignals = currentStoreSignals.filter((signal) => {
    if (snapshotIds.has(signal.id)) return false;
    if (!isOpenFeedSignal(signal)) return false;
    if (!signalMatchesRadarDisplayMode(signal, radarDisplayMode)) return false;
    const receivedAt = signalReceivedAtById[signal.id] ?? signalUpdatedAtMs(signal);
    return receivedAt > snapshotReceivedAt;
  });
  return [...realtimeSignals, ...snapshotOpenSignals];
}

export function filterSignalsForRadarDisplayMode(
  signals: RadarSignal[],
  radarDisplayMode?: RadarDisplayMode | null
): RadarSignal[] {
  return signals.filter((signal) => signalMatchesRadarDisplayMode(signal, radarDisplayMode));
}

export function signalMatchesRadarDisplayMode(
  signal: RadarSignal,
  radarDisplayMode?: RadarDisplayMode | null
): boolean {
  if (!radarDisplayMode || radarDisplayMode === "all_market_opportunities") return true;
  if (radarDisplayMode === "blocked") return isBlockedSignal(signal);
  if (radarDisplayMode === "watchlist") return signal.execution_gate?.feed_kind === "watchlist";
  if (radarDisplayMode === "market_ideas") return signal.execution_gate?.feed_kind === "market_idea";
  if (radarDisplayMode === "execution_ready" || radarDisplayMode === "execution_signals") {
    return isHotSignal(signal);
  }
  return true;
}

export function isRadarDashboardQueryKey(queryKey: unknown): boolean {
  return Array.isArray(queryKey)
    && queryKey[0] === "fastapi"
    && queryKey[1] === "radar"
    && queryKey[2] === "dashboard";
}

export function isSignalHistoryQueryKey(queryKey: unknown): boolean {
  return Array.isArray(queryKey)
    && queryKey[0] === "fastapi"
    && queryKey[1] === "signals"
    && queryKey[2] === "history";
}

function isBlockedSignal(signal: RadarSignal): boolean {
  if (signal.execution_gate?.feed_kind === "blocked") return true;
  if (signal.details_view) return signal.details_view.primary_status === "blocked";
  return signal.risk_gate_status === "failed"
    || signal.rr_status === "failed"
    || signal.can_enter === false;
}

function isHotSignal(signal: RadarSignal): boolean {
  const gate = signal.execution_gate;
  if (!gate) return false;
  if (gate.feed_kind === "blocked") return false;
  if (gate.reasons.some((reason) => reason.severity === "blocker")) return false;
  if (gate.reasons.some((reason) => reason.code === "score_below_execution_threshold")) return false;
  return gate.can_enter_now === true || gate.can_arm_pending === true;
}

function signalUpdatedAtMs(signal: RadarSignal): number {
  const updatedAt = Date.parse(signal.updated_at);
  if (Number.isFinite(updatedAt)) return updatedAt;
  const createdAt = Date.parse(signal.created_at);
  return Number.isFinite(createdAt) ? createdAt : 0;
}
