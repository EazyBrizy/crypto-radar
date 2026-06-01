import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RadarSignal } from "@/types";
import { SignalDetails } from "./SignalDetails";

vi.mock("next/dynamic", () => ({
  default: () => () => null
}));

const signal: RadarSignal = {
  id: "sig_1",
  symbol: "ETHUSDT",
  exchange: "bybit",
  strategy: "volatility_squeeze_breakout",
  direction: "long",
  confidence: 0.84,
  risk_reward: 2.5,
  first_target_rr: 1,
  final_target_rr: 2.5,
  selected_rr: 2.5,
  selected_rr_target: "final",
  min_rr_ratio: 1.5,
  urgency: "medium",
  status: "actionable",
  score: 84,
  timeframe: "15m",
  entry_min: 2_100,
  entry_max: 2_105,
  stop_loss: 2_060,
  take_profit_1: 2_150,
  take_profit_2: 2_200,
  explanation: ["Breakout confirmed"],
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
    total: 84
  },
  status_reason: null,
  quality: null,
  regime: null,
  setup: null,
  confirmation: {
    passed: false,
    checks: [
      {
        name: "no_trade_filter",
        status: "failed",
        score: null,
        reason: "high_spread",
        metadata: {}
      }
    ]
  },
  invalidation: null,
  exit_plan: null,
  auto_entry: null,
  trade_plan: {
    version: "v1",
    entry: {
      price: 2_102,
      min_price: 2_100,
      max_price: 2_105,
      source: "aggressive_breakout",
      metadata: { entry_type: "aggressive_breakout" }
    },
    stop_loss: 2_060,
    targets: [
      { label: "TP1", price: 2_150, r_multiple: 1, action: "partial_close", close_percent: 40, source: "rr", metadata: {} },
      { label: "TP2", price: 2_200, r_multiple: 2, action: "reduce_runner", close_percent: 30, source: "rr", metadata: {} },
      { label: "TP3", price: 2_240, r_multiple: 2.8, action: "full_close", close_percent: 30, source: "range_measured_move", metadata: {} }
    ],
    invalidation: {
      price: 2_060,
      hard_stop: 2_060,
      conditions: ["Breakout fails"],
      metadata: {}
    },
    risk_rules: {
      risk_reward: 2.8,
      first_target_rr: 1,
      final_target_rr: 2.8,
      selected_rr: 2.8,
      selected_rr_target: "final",
      min_rr_ratio: 1.5,
      metadata: {}
    },
    metadata: {}
  },
  edge: {
    status: "positive",
    sample_size: 75,
    min_sample_size: 50,
    winrate: 0.61,
    avg_win_r: 1.8,
    avg_loss_r: -1,
    expectancy_r: 0.45,
    expectancy_after_costs_r: 0.37,
    profit_factor: 1.6,
    confidence_score: 0.72,
    source: "outcome",
    score_bucket: "80-89",
    metadata: {}
  },
  no_trade_filter: {
    enabled: true,
    blocked: true,
    hard_block: true,
    blockers: ["high_spread"],
    warnings: ["virtual-only recommended"],
    checks: [],
    metadata: {}
  },
  created_at: "2026-05-31T07:00:00.000Z",
  updated_at: "2026-05-31T07:00:00.000Z",
  expires_at: "2026-05-31T08:00:00.000Z"
};

describe("SignalDetails", () => {
  it("renders trade plan, edge metrics and risk blockers", () => {
    render(
      <SignalDetails
        busy={false}
        executionPreview={null}
        onPaperTrade={vi.fn()}
        onReject={vi.fn()}
        signal={signal}
      />
    );

    expect(screen.getByText("Trade Plan")).toBeInTheDocument();
    expect(screen.getAllByText(/TP3/u).length).toBeGreaterThan(0);
    expect(screen.getByText("Edge Snapshot")).toBeInTheDocument();
    expect(screen.getByText("61%")).toBeInTheDocument();
    expect(screen.getByText("Risk blockers / warnings")).toBeInTheDocument();
    expect(screen.getAllByText("high_spread").length).toBeGreaterThan(0);
  });
});
