export const performanceBudgets = {
  chartComponentsLazyLoaded: true,
  heavyAnalyticsChunked: true,
  initialDashboardRenderMs: 1_500,
  largeListsVirtualized: true,
  routeBundleSplitting: true,
  signalEventApplyMs: 100,
  tradeJournalServerFiltered: true,
  websocketReconnectAutomatic: true
} as const;

export function warnIfRealtimeEventExceedsBudget(eventType: string, startedAt: number) {
  if (typeof performance === "undefined") return;
  const durationMs = performance.now() - startedAt;
  if (durationMs <= performanceBudgets.signalEventApplyMs) return;
  console.warn(`[performance] ${eventType} update took ${Math.round(durationMs)}ms`);
}
