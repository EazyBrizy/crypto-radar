import { describe, expect, it } from "vitest";

import type { RadarSignal } from "./types";
import { isOpenFeedSignal, isSignalExpired, signalTtlLabel } from "./utils";

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "bybit",
  strategy: "trend_pullback_continuation",
  direction: "long",
  confidence: 0.82,
  risk_reward: 2,
  first_target_rr: 1.5,
  final_target_rr: 2,
  selected_rr: 2,
  selected_rr_target: "final",
  min_rr_ratio: 2,
  urgency: "medium",
  status: "active",
  score: 82,
  timeframe: "15m",
  entry_min: 100,
  entry_max: 101,
  stop_loss: 98,
  take_profit_1: 104,
  take_profit_2: null,
  explanation: [],
  risks: [],
  score_breakdown: {
    trend_score: 80,
    volume_score: 80,
    liquidity_score: 80,
    orderbook_score: 80,
    risk_reward_score: 80,
    volatility_score: 80,
    overheat_penalty: 0,
    news_event_risk_penalty: 0,
    total: 82
  },
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: null,
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  created_at: "2026-05-29T09:00:00.000Z",
  updated_at: "2026-05-29T09:00:00.000Z",
  expires_at: "2026-05-29T10:00:00.000Z"
};

describe("signal expiry utilities", () => {
  it("keeps fresh open signals actionable", () => {
    const now = Date.parse("2026-05-29T09:30:00.000Z");

    expect(isSignalExpired(baseSignal, now)).toBe(false);
    expect(isOpenFeedSignal(baseSignal, now)).toBe(true);
    expect(signalTtlLabel(baseSignal, now)).toBe("TTL 30m");
  });

  it("removes expired signals from the open feed", () => {
    const now = Date.parse("2026-05-29T10:00:01.000Z");

    expect(isSignalExpired(baseSignal, now)).toBe(true);
    expect(isOpenFeedSignal(baseSignal, now)).toBe(false);
    expect(signalTtlLabel(baseSignal, now)).toBe("TTL expired");
  });
});
