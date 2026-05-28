export interface ReconnectPolicy {
  nextDelay: (attempt: number) => number;
}

export function createReconnectPolicy(options: {
  baseDelayMs?: number;
  maxDelayMs?: number;
  jitterRatio?: number;
} = {}): ReconnectPolicy {
  const baseDelayMs = options.baseDelayMs ?? 1_000;
  const maxDelayMs = options.maxDelayMs ?? 15_000;
  const jitterRatio = options.jitterRatio ?? 0.2;

  return {
    nextDelay(attempt: number) {
      const exponentialDelay = Math.min(baseDelayMs * 2 ** Math.max(0, attempt - 1), maxDelayMs);
      const jitter = exponentialDelay * jitterRatio * Math.random();
      return Math.round(exponentialDelay + jitter);
    }
  };
}
