import { describe, expect, it } from "vitest";

import type { RadarSignal } from "@/types";
import {
  canShowEnterButton,
  isExecutionCandidateStatus,
  isExecutionReady,
  isMarketOpportunity,
  isTerminalSignalStatus,
  isWaitingEntry
} from "./signal-status";

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
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z"
};

describe("signal status domain helper", () => {
  it("treats active as market opportunity and waiting entry, not execution-ready", () => {
    expect(isMarketOpportunity("active")).toBe(true);
    expect(isWaitingEntry("active")).toBe(true);
    expect(isExecutionCandidateStatus("active")).toBe(false);
    expect(isExecutionReady("active")).toBe(false);
    expect(canShowEnterButton(baseSignal)).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, can_enter: true })).toBe(false);
  });

  it("marks entry-touched/actionable as execution candidates and invalidated/expired as terminal", () => {
    expect(isExecutionCandidateStatus("entry_touched")).toBe(true);
    expect(isExecutionCandidateStatus("actionable")).toBe(true);
    expect(isExecutionCandidateStatus("confirmed")).toBe(true);
    expect(isTerminalSignalStatus("invalidated")).toBe(true);
    expect(isTerminalSignalStatus("expired")).toBe(true);
  });

  it("requires backend permission for actionable and entry-touched signals", () => {
    expect(canShowEnterButton({ ...baseSignal, status: "actionable" })).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, status: "entry_touched" })).toBe(false);
    expect(canShowEnterButton({ ...baseSignal, status: "actionable", can_enter: true })).toBe(true);
    expect(canShowEnterButton({ ...baseSignal, status: "entry_touched", can_enter: true })).toBe(true);
    expect(canShowEnterButton({ ...baseSignal, status: "entry_touched", can_enter: false })).toBe(false);
  });

  it("accepts decision snapshots only when execution is allowed and unblocked", () => {
    const signal: RadarSignal = {
      ...baseSignal,
      status: "actionable",
      decision: {
        setup_valid: true,
        trade_plan_valid: true,
        market_context_score: 80,
        signal_actionable: true,
        execution_allowed_virtual: true,
        execution_allowed_real: null,
        blockers: [],
        warnings: []
      }
    };

    expect(canShowEnterButton(signal)).toBe(true);
    expect(canShowEnterButton({
      ...signal,
      decision: {
        ...signal.decision!,
        blockers: [{
          code: "risk_gate",
          message: "Blocked by risk profile",
          source: "risk",
          severity: "blocker",
          scope: "virtual",
          metadata: {}
        }]
      }
    })).toBe(false);
  });
});
