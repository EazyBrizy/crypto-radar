import { useUiStore } from "./ui-store";
import type { RealtimeConnectionStatus } from "@/realtime/event-types";

export const useActivePage = () => useUiStore((state) => state.page);
export const useActiveTradeTab = () => useUiStore((state) => state.tradeTab);
export const useRadarFilter = () => useUiStore((state) => state.signalFilter);
export const useRealtimeConnectionStatus = () => useUiStore((state) => state.connectionStatus);
export const useSelectedSignalId = () => useUiStore((state) => state.selectedSignalId);
export const useSelectedTradeId = () => useUiStore((state) => state.selectedTradeId);
export const useSidebarOpen = () => useUiStore((state) => state.sidebarOpen);

export const tradingDisabledStatuses = new Set<RealtimeConnectionStatus>([
  "closed",
  "delayed",
  "error",
  "offline",
  "unauthorized"
]);

export function isTradingActionDisabled(status: RealtimeConnectionStatus): boolean {
  return tradingDisabledStatuses.has(status);
}

export function getLastRealtimeUpdateAt(lastEventAt: number | null, lastHeartbeatAt: number | null): number | null {
  if (lastEventAt === null) return lastHeartbeatAt;
  if (lastHeartbeatAt === null) return lastEventAt;
  return Math.max(lastEventAt, lastHeartbeatAt);
}

export function formatRealtimeAge(updatedAt: number | null, now = Date.now()): string {
  if (updatedAt === null) return "waiting for data";

  const ageMs = Math.max(0, now - updatedAt);
  if (ageMs < 1_000) return `${ageMs}ms ago`;
  if (ageMs < 60_000) return `${Math.round(ageMs / 1_000)}s ago`;
  return `${Math.round(ageMs / 60_000)}m ago`;
}

export const useTradingActionsDisabled = () => useUiStore((state) => isTradingActionDisabled(state.connectionStatus));
