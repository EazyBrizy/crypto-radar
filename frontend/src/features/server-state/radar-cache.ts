import type { RadarResponse, RadarSignal, RadarSummary } from "@/types";
import { isOpenFeedSignal } from "@/utils";

export function buildRadarSummaryFrontend(signals: RadarSignal[]): RadarSummary {
  return {
    total_signals: signals.length,
    execution_ready_signals: signals.filter((signal) => signal.details_view?.can_enter_now === true).length,
    high_confidence_signals: signals.filter((signal) => signal.score >= 80).length,
    positive_edge_signals: signals.filter((signal) => signal.edge?.status === "positive").length,
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
  signalReceivedAtById: Record<string, number> = {}
): RadarSignal[] {
  const currentById = new Map(currentStoreSignals.map((signal) => [signal.id, signal]));
  const snapshotOpenSignals = snapshotSignals
    .filter((signal) => isOpenFeedSignal(signal, snapshotReceivedAt))
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
    const receivedAt = signalReceivedAtById[signal.id] ?? signalUpdatedAtMs(signal);
    return receivedAt > snapshotReceivedAt;
  });
  return [...realtimeSignals, ...snapshotOpenSignals];
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
  if (signal.details_view) return signal.details_view.primary_status === "blocked";
  return signal.risk_gate_status === "failed"
    || signal.rr_status === "failed"
    || signal.can_enter === false;
}

function signalUpdatedAtMs(signal: RadarSignal): number {
  const updatedAt = Date.parse(signal.updated_at);
  if (Number.isFinite(updatedAt)) return updatedAt;
  const createdAt = Date.parse(signal.created_at);
  return Number.isFinite(createdAt) ? createdAt : 0;
}
