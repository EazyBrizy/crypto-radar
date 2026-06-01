import { afterEach, describe, expect, it, vi } from "vitest";

import type { RadarSignal } from "./types";
import {
  isOpenFeedSignal,
  isRiskRewardBlocked,
  isSignalExpired,
  riskRewardWarningReason,
  signalAge,
  signalTtlLabel,
  signalUpdatedAge
} from "./utils";

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
  afterEach(() => {
    vi.useRealTimers();
  });

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

  it("separates original signal age from latest update age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-29T09:58:00.000Z"));

    const refreshedSignal = {
      ...baseSignal,
      updated_at: "2026-05-29T09:57:30.000Z"
    };

    expect(signalAge(refreshedSignal)).toBe("58m ago");
    expect(signalUpdatedAge(refreshedSignal)).toBe("just now");
  });
});

describe("risk/reward display utilities", () => {
  it("treats failed legacy RR metadata as a virtual warning instead of a hard block", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      selected_rr: 0.8,
      min_rr_ratio: 1.5,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "risk_reward_guard",
            status: "failed",
            score: 0.8,
            reason: "Risk/reward blocked: nearest target is below minimum",
            metadata: { risk_reward_blocked: true }
          }
        ]
      }
    };

    expect(isRiskRewardBlocked(signal)).toBe(false);
    expect(riskRewardWarningReason(signal)).toContain("Risk/reward warning");
    expect(riskRewardWarningReason(signal)?.toLowerCase()).not.toContain("blocked");
  });

  it("keeps explicitly hard RR failures as blockers", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      confirmation: {
        passed: false,
        checks: [
          {
            name: "risk_reward_guard",
            status: "failed",
            score: 0.8,
            reason: "Risk/reward blocked: nearest target is below minimum",
            metadata: { risk_reward_blocked: true, risk_reward_guard_mode: "hard" }
          }
        ]
      }
    };

    expect(isRiskRewardBlocked(signal)).toBe(true);
    expect(riskRewardWarningReason(signal)).toBeNull();
  });

  it("treats explicit off RR guard as metadata-only", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      selected_rr: 0.8,
      min_rr_ratio: 1.5,
      confirmation: {
        passed: true,
        checks: [
          {
            name: "risk_reward_guard",
            status: "skipped",
            score: 0.8,
            reason: "Risk/reward guard is off: nearest target is 0.80R",
            metadata: {
              risk_reward_guard_mode: "off",
              risk_reward_warning: false,
              risk_reward_blocked: false,
              selected_rr: 0.8,
              min_rr_ratio: 1.5
            }
          }
        ]
      }
    };

    expect(isRiskRewardBlocked(signal)).toBe(false);
    expect(riskRewardWarningReason(signal)).toBeNull();
  });
});
