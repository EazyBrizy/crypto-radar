import { describe, expect, it, vi } from "vitest";

import type { RadarSignal, SignalStatus } from "@/types";
import { canArmAutoEntry, canSendPaperTrade, shouldRequestExecutionPreview } from "./RadarRoute";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() })
}));

const baseSignal: RadarSignal = {
  id: "sig_1",
  symbol: "BTCUSDT",
  exchange: "bybit",
  strategy: "trend_pullback_continuation",
  direction: "long",
  confidence: 0.82,
  risk_reward: 2,
  first_target_rr: 1,
  final_target_rr: 2,
  selected_rr: 2,
  selected_rr_target: "final",
  min_rr_ratio: 1.5,
  urgency: "medium",
  status: "ready",
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
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z"
};

function signalWithStatus(status: SignalStatus): RadarSignal {
  return { ...baseSignal, status };
}

describe("shouldRequestExecutionPreview", () => {
  it("keeps Reality Check populated for armed and pending Trend Pullback statuses", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("new"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("watchlist"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", false)).toBe(true);
    expect(shouldRequestExecutionPreview(signalWithStatus("wait_for_pullback"), "open", false)).toBe(true);
  });

  it("does not preview history, blocked UI state, or terminal signals", () => {
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "history", false)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("ready"), "open", true)).toBe(false);
    expect(shouldRequestExecutionPreview(signalWithStatus("expired"), "open", false)).toBe(false);
    expect(shouldRequestExecutionPreview(null, "open", false)).toBe(false);
  });
});

describe("paper trade eligibility", () => {
  it("does not allow active market opportunities to enter", () => {
    expect(canSendPaperTrade(signalWithStatus("active"))).toBe(false);
  });

  it("allows paper trade only after backend execution permission", () => {
    expect(canSendPaperTrade(signalWithStatus("actionable"))).toBe(false);
    expect(canSendPaperTrade(signalWithStatus("entry_touched"))).toBe(false);
    expect(canSendPaperTrade({ ...signalWithStatus("actionable"), can_enter: true })).toBe(true);
    expect(canSendPaperTrade({ ...signalWithStatus("entry_touched"), can_enter: true })).toBe(true);
    expect(canSendPaperTrade({ ...signalWithStatus("entry_touched"), can_enter: false })).toBe(false);
  });

  it("does not turn soft or legacy RR warnings into enter permission", () => {
    const lowRrSignal: RadarSignal = {
      ...baseSignal,
      selected_rr: 0.8,
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

    expect(canArmAutoEntry(lowRrSignal)).toBe(true);
    expect(canSendPaperTrade(lowRrSignal)).toBe(false);
  });
});
