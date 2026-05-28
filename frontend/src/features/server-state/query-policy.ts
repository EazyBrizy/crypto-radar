export const serverStatePolicy = {
  defaultStaleTimeMs: 15_000,
  realtimeStaleTimeMs: 2_000,
  reconciliationIntervalMs: 60_000,
  staticStaleTimeMs: 5 * 60_000,
  backgroundRefreshMs: 5_000,
  slowBackgroundRefreshMs: 60_000,
  gcTimeMs: 10 * 60_000
};
